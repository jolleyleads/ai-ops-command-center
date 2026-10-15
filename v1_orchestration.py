import json
import os
import re
import hashlib
import threading
from contextlib import contextmanager
from sqlalchemy import text as sql_text
from datetime import datetime, timedelta, timezone
from flask import jsonify, request
from app import app, db
from src.grounded_reply import routine_answer
from src.automatic_reply_router import current_reply_text
from src.company_identity import owned_host, name_key
from src.enrichment import enrich_lead, validated_payload
from src.email_validation import apply_email_domain_check
from outreach_bridge import QUEUE_MIN_SCORE, _candidate_urls, _clean, _outreach_search, _evidence_for_storage, _evidence_score, _public_contact_evidence, _same_company_domain, _valid_email, _verified
from outreach_automation import FIRST_FOLLOWUP_DAYS, OutreachLead, OutreachBookingAttempt, OperatorAuditEvent, _audit_actor, _draft_email, _gmail_thread_reply_state, _persist_reply_evidence, _route_persisted_reply, _safe_send, _store_qualification

AUTOSEND_ENABLED = os.getenv("OUTREACH_AUTOSEND_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
EMAIL_SCAN_RE = re.compile(r"(?i)(?<![\w.+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![\w.-])")

DISALLOWED_OUTREACH_MAILBOXES = {
    "abuse","careers","compliance","dmca","donotreply","grievance","hr","humanresources",
    "jobs","legal","medicalrecords","noreply","postmaster","privacy","recruiting","recruitment","webmaster",
}


def _purpose_mailbox_allowed(email):
    value=_clean(email,500).lower()
    if "@" not in value:
        return False
    local=value.rsplit("@",1)[0]
    canonical=re.sub(r"[^a-z0-9]+","",local)
    return canonical not in DISALLOWED_OUTREACH_MAILBOXES


def _verified_public_email(result):
    """Return only a source-visible email on the prospect's explicit company website domain.

    Third-party evidence may verify intent, but it can never establish the outreach recipient domain.
    """
    website = _clean(result.get("website"), 1800)
    if not website.startswith(("http://", "https://")):
        return "", ""
    company_urls = [website]

    # Search snippets and old stored emails are discovery hints, not current
    # contact proof. Always re-fetch the company pages before qualification.
    contact_result = _public_contact_evidence(result)
    rows = contact_result[0] if isinstance(contact_result, tuple) else contact_result
    company=result.get("company") or result.get("name") or result.get("business_name") or result.get("candidate_name") or result.get("title")
    location=result.get("contact_location") or result.get("target_location") or result.get("location") or ""
    query=result.get("query") or result.get("business_need") or ""
    enrichment=enrich_lead({"company":company,"website":website,"target_location":location,"query":query},rows or [],email_allowed=_purpose_mailbox_allowed)
    apply_email_domain_check(enrichment)
    if (result.get('_campaign_context') or {}).get('require_decision_maker') is True:
        assessment=enrichment.get('contact_assessment') or {}
        if assessment.get('email_person_status')!='same_source_card' or assessment.get('decision_maker_status')!='source_supported':
            if enrichment.get('fields',{}).get('email'):
                enrichment['fields']['email']['validated']=False
            assessment.setdefault('reason_codes',[]).append('NAMED_DECISION_MAKER_EMAIL_REQUIRED')
    result["_contact_enrichment"]=enrichment
    validated=validated_payload(enrichment)
    email=_valid_email(validated.get("email"));url=_clean(validated.get("email_source_url"),1800)
    result["_contact_name"]=""
    if email and _purpose_mailbox_allowed(email) and _same_company_domain(email,company_urls) and owned_host(url,website):
        assessment=enrichment.get("contact_assessment") or {}
        if assessment.get("decision_maker_status")=="source_supported" and assessment.get("person_email")==email and assessment.get("email_person_status")=="same_source_card":
            result["_contact_name"]=validated.get("decision_maker") or ""
        source=next((row for row in rows or [] if row.get("url")==url),{})
        result["_contact_identity"]={"company_identity":source.get("company_identity") or {"company_name":company},"identity_version":"company-domain-v1","contact_location":location,"contact_assessment":assessment,"enrichment":enrichment}
        return email,url
    return "",""


def _evidence_with_contact(result, email, email_source):
    observed = datetime.now(timezone.utc).isoformat()
    evidence = []
    for raw in _evidence_for_storage(result):
        if isinstance(raw, dict):
            item = dict(raw); item.setdefault("observed_at", observed); evidence.append(item)
    if email and email_source:
        evidence.append({"email": email, "url": email_source, "source": "verified_public_contact", "observed_at": observed,**(result.get("_contact_identity") or {})})
    elif isinstance(result.get("_contact_enrichment"),dict):
        enrichment=result["_contact_enrichment"]
        source=(enrichment.get("fields",{}).get("email") or {}).get("source_url") or result.get("website") or result.get("url") or ""
        evidence.append({"url":source,"source":"contact_validation_receipt","observed_at":observed,"enrichment":enrichment,"contact_assessment":enrichment.get("contact_assessment") or {},"contact_status":"no_validated_email"})
    return evidence


_discovery_locks = [threading.Lock() for _ in range(64)]


@contextmanager
def discovery_lock(company, source_url):
    """Serialize one company/source across transactions and PostgreSQL workers."""
    digest = hashlib.sha256((company.casefold()+'|'+source_url).encode()).digest()
    key = int.from_bytes(digest[:8], 'big', signed=True)
    if db.engine.dialect.name != 'postgresql':
        lock = _discovery_locks[key % len(_discovery_locks)]
        acquired = lock.acquire(blocking=False)
        try:yield acquired
        finally:
            if acquired:lock.release()
        return
    # A separate connection keeps the session lock across workflow commits.
    with db.engine.connect() as connection:
        acquired = connection.execute(sql_text('SELECT pg_try_advisory_lock(:key)'), {'key':key}).scalar()
        try:yield bool(acquired)
        finally:
            connection.rollback()
            if acquired:
                connection.execute(sql_text('SELECT pg_advisory_unlock(:key)'), {'key':key})
                connection.commit()


def campaign_context(payload, result):
    query = _clean(payload.get("query") or payload.get("goal") or payload.get("intent_signal"), 1000)
    return {"target_location": _clean(payload.get("location") or result.get("contact_location"), 300),
            "query": query, "intent_signal": query,
            "business_type": _clean(payload.get("business_type"), 300),
            "candidate_type": _clean(result.get("category") or result.get("type"), 300),
            "require_decision_maker": payload.get("require_decision_maker") is True or bool(re.search(r"(?i)\bdecision[ -]?makers?\b", query))}


def unfinished_lead_reasons(qualification,mailbox):
    # An opt-out mailbox receipt is informational: source-validated contacts
    # can still fail another qualification check and must recover that check.
    provider=[r for r in mailbox.get('reason_codes') or [] if r!='HUNTER_NOT_ENABLED']
    return provider or qualification.get('reason_codes') or ['CONTACT_EVIDENCE_MISSING']


def resume_discovery_lead(lead, result, lease_valid=None):
    """Refresh held discovery only, never rewrite a sent conversation."""
    email, source = _verified_public_email(result)
    if lease_valid and not lease_valid():
        return {'ok':False,'reason_codes':['RECOVERY_LEASE_LOST']}
    assessment = (result.get('_contact_enrichment') or {}).get('contact_assessment') or {}
    mailbox = assessment.get('mailbox_validation') or {}
    lead.contact_email = email
    lead.contact_name = _clean(result.get('_contact_name'), 300)
    evidence = _evidence_with_contact(result, email, source)
    if result.get('_campaign_context'):
        evidence.append({'source': 'campaign_context', 'context': result['_campaign_context']})
    lead.evidence_json = json.dumps(evidence)
    db.session.commit()
    receipt = _store_qualification(lead)
    if not receipt.get('ok') or not email:
        return {'ok': False, 'reason_codes': unfinished_lead_reasons(receipt,mailbox)}
    drafted = _draft_email(lead)
    if not drafted.get('ok'):
        return {'ok': False, 'reason_codes': ['DRAFT_FAILED']}
    if lease_valid and not lease_valid():
        return {'ok':False,'reason_codes':['RECOVERY_LEASE_LOST']}
    lead.subject, lead.body = drafted['subject'], drafted['body']
    lead.status = 'drafted'
    lead.last_error = ''
    db.session.commit()
    # Recovery prepares drafts. Sending requires a subsequent authorized campaign
    # or operator action, so clearing quota cannot fire an old campaign unexpectedly.
    return {'ok': True, 'stage': 'drafted'}


def orchestrate_discovery(payload):
    summary={"enabled":True,"autosend_enabled":AUTOSEND_ENABLED,"eligible":0,"saved":0,"qualified":0,"drafted":0,"sent":0,"skipped":[]}
    try: outreach_limit=max(0,int(payload.get("outreach_limit") or 0))
    except (TypeError,ValueError): outreach_limit=0
    if not _outreach_search(payload):
        summary["enabled"]=False; summary["paused_reason"]="not_b2b_outreach_search"; return summary
    for result in payload.get("results") or []:
        if outreach_limit and summary["sent"]>=outreach_limit: break
        if not isinstance(result,dict): continue
        company=_clean(result.get("company") or result.get("name") or result.get("business_name") or result.get("title"),300)
        score=_evidence_score(result)
        if not company or score<QUEUE_MIN_SCORE or not _verified(result): continue
        summary["eligible"]+=1
        urls=_candidate_urls(result); source_url=urls[0] if urls else ""
        if not source_url:
            summary["skipped"].append({"company":company,"reason":"missing_source_url"}); continue
        with discovery_lock(company,source_url) as acquired:
            if not acquired:
                summary['skipped'].append({'company':company,'reason':'discovery_in_progress'})
                continue
            existing=OutreachLead.query.filter_by(company=company,source_url=source_url).first()
            result={**result,"contact_location":payload.get("location") or result.get("contact_location") or result.get("location"),"query":payload.get("query") or payload.get("goal") or payload.get("intent_signal"),"_campaign_context":campaign_context(payload,result)}
            if existing:
                from lead_recovery import LeadRecovery, schedule_recovery
                held = db.session.get(LeadRecovery, existing.id)
                if existing.status=='needs_evidence' and not existing.gmail_message_id and not held:
                    held=schedule_recovery(existing,result,['CONTACT_EVIDENCE_MISSING'])
                if held and existing.status in {'needs_evidence','qualified','drafted'}:
                    summary["skipped"].append({"company":company,"reason":"recovery_scheduled","lead_id":existing.id,"recovery_state":held.state})
                else:
                    summary["skipped"].append({"company":company,"reason":"already_queued","lead_id":existing.id})
                continue
            email,email_source=_verified_public_email(result)
            evidence=_evidence_with_contact(result,email,email_source)
            evidence.append({'source':'campaign_context','context':result['_campaign_context']})
            lead=OutreachLead(company=company,contact_email=email,contact_name=_clean(result.get("_contact_name"),300),location=_clean(result.get("location") or payload.get("location"),300),source_url=source_url,evidence_json=json.dumps(evidence),score=score,verification=_clean(result.get("verification"),100) or "SOURCE_VERIFIED",status="needs_evidence")
            db.session.add(lead); db.session.commit(); summary["saved"]+=1
            qualification=_store_qualification(lead)
            if not qualification.get("ok"):
                from lead_recovery import schedule_recovery
                mailbox=(result.get('_contact_enrichment') or {}).get('contact_assessment',{}).get('mailbox_validation',{})
                schedule_recovery(lead,result,unfinished_lead_reasons(qualification,mailbox))
                summary["skipped"].append({"company":company,"lead_id":lead.id,"reason":"qualification_failed","reason_codes":qualification.get("reason_codes") or []}); continue
            summary["qualified"]+=1
            if not email:
                summary["skipped"].append({"company":company,"lead_id":lead.id,"reason":"no_verified_public_email"}); continue
            drafted=_draft_email(lead)
            if not drafted.get("ok"):
                from lead_recovery import schedule_recovery
                schedule_recovery(lead,result,['DRAFT_FAILED'])
                lead.last_error=_clean(drafted.get("error"),2000); db.session.commit(); summary["skipped"].append({"company":company,"lead_id":lead.id,"reason":"draft_failed"}); continue
            lead.subject=drafted["subject"]; lead.body=drafted["body"]; lead.status="drafted"; lead.last_error=""; db.session.commit(); summary["drafted"]+=1
            if not AUTOSEND_ENABLED:
                summary["skipped"].append({"company":company,"lead_id":lead.id,"reason":"autosend_disabled","status":"drafted"}); continue
            execution=_safe_send(lead,kind="initial",sequence=0,subject=lead.subject,body=lead.body)
            if not execution.get("ok"):
                lead.last_error=_clean(execution,2000); db.session.commit(); summary["skipped"].append({"company":company,"lead_id":lead.id,"reason":"safe_send_failed","stage":_clean(execution.get("stage"),100),"gate_reasons":((execution.get("gate") or {}).get("reasons") or []),"receipt_reasons":((execution.get("send_receipt") or {}).get("reasons") or []),"provider_error":_clean(execution.get("error"),500)}); continue
            receipt=execution.get("send_receipt") or {}; now=datetime.utcnow()
            lead.gmail_message_id=_clean(receipt.get("message_id"),255); lead.gmail_thread_id=_clean(receipt.get("thread_id"),255); lead.sent_at=now; lead.follow_up_due_at=now+timedelta(days=FIRST_FOLLOWUP_DAYS); lead.status="sent"; lead.last_error=""; lead.updated_at=now; db.session.commit(); summary["sent"]+=1
            summary["skipped"].append({"company":company,"lead_id":lead.id,"status":"sent","message_id":lead.gmail_message_id,"thread_id":lead.gmail_thread_id})
    return summary


def scan_real_inbound_replies():
    now=datetime.utcnow()
    leads=OutreachLead.query.filter(OutreachLead.gmail_thread_id.isnot(None),OutreachLead.gmail_thread_id!="",OutreachLead.status.in_(["sent","followup_sent","interested","question","responded","booking_ready","booked"])).order_by(OutreachLead.id.asc()).all()
    processed=[]
    for lead in leads:
        reply=_gmail_thread_reply_state(lead.gmail_thread_id)
        if not reply.get("ok"):
            processed.append({"lead_id":lead.id,"ok":False,"stage":"reply_check_failed","reason":reply.get("reason"),"error":reply.get("error")}); continue
        if not reply.get("replied"):
            processed.append({"lead_id":lead.id,"ok":True,"stage":"no_reply"}); continue
        # Only the known prospect's messages can advance their workflow.
        evidence=[x for x in reply.get("reply_evidence") or [] if str(x.get("from_email") or "").strip().lower()==lead.contact_email.strip().lower()]
        evidence.sort(key=lambda x:int(x.get("internal_date") or 0))
        if not evidence:
            processed.append({"lead_id":lead.id,"ok":True,"stage":"no_prospect_reply"});continue
        latest=evidence[-1];message_id=_clean(latest.get("message_id"),255)
        handled=OperatorAuditEvent.query.filter_by(lead_id=lead.id,action="inbound_processed").all()
        markers=[x for x in handled if json.loads(x.request_json).get("message_id")==message_id]
        if message_id and markers:
            last=max(markers,key=lambda x:x.id)
            previous_stage=json.loads(last.result_json).get("stage")
            # A newly supported FAQ may resume a prior review-only route. Its
            # persisted message identity still owns send idempotency.
            from src.grounded_reply import scheduling_request
            resumable = routine_answer(current_reply_text(latest.get("text"))) or (previous_stage == "unclear" and scheduling_request(current_reply_text(latest.get("text"))))
            if previous_stage not in {"unclear","question"} or not resumable:
                processed.append({"lead_id":lead.id,"ok":True,"stage":"already_processed"});continue
        if not message_id:
            processed.append({"lead_id":lead.id,"ok":False,"stage":"missing_message_id"});continue
        # Older manually imported conversations have a confirmed booking receipt
        # but predate the scanner's per-message marker. Preserve their completion.
        confirmed=OutreachBookingAttempt.query.filter_by(lead_id=lead.id,reply_message_id=message_id,status="confirmed").first()
        if confirmed:
            lead.status="booked";lead.follow_up_due_at=None
            if lead.last_error=="QUALIFICATION_REQUIRED_FOR_BOOKING":lead.last_error=""
            _audit_actor(lead.id,"inbound_processed",{"message_id":message_id},{"stage":"already_booked","event_id":confirmed.event_id},"scheduler")
            db.session.commit()
            processed.append({"lead_id":lead.id,"ok":True,"stage":"already_booked"});continue
        reply=dict(reply,reply_evidence=evidence)
        _persist_reply_evidence(lead,reply); routed=_route_persisted_reply(lead,reply,now); lead.updated_at=now
        if routed.get("ok"):
            _audit_actor(lead.id,"inbound_processed",{"message_id":message_id},{"stage":routed.get("stage")},"scheduler")
        db.session.commit()
        processed.append({"lead_id":lead.id,"ok":routed.get("ok") is True,"stage":routed.get("stage"),"classification":(routed.get("classification") or {}).get("classification"),"thread_id":lead.gmail_thread_id})
    return {"ok":all(x.get("ok") for x in processed) if processed else True,"checked":len(leads),"processed":processed}


@app.after_request
def v1_discovery_orchestration_hook(response):
    if request.path!="/api/smart-search" or request.method not in {"GET","POST"} or response.status_code!=200 or not response.is_json: return response
    try:
        payload=response.get_json(silent=True) or {}; payload["outreach_automation"]=orchestrate_discovery(payload); response.set_data(app.json.dumps(payload)); response.headers["Content-Type"]="application/json"; response.headers["Content-Length"]=str(len(response.get_data()))
    except Exception as exc: app.logger.exception("V1_DISCOVERY_ORCHESTRATION_ERROR %s",type(exc).__name__)
    return response


@app.route("/api/outreach/process-inbound",methods=["POST"])
def process_inbound_replies():
    import hmac
    expected=os.getenv("OUTREACH_CRON_TOKEN","").strip(); supplied=request.headers.get("X-Outreach-Cron-Token","")
    if not expected or not supplied or not hmac.compare_digest(expected,supplied): return jsonify({"ok":False,"error":"unauthorized"}),401
    result=scan_real_inbound_replies(); return jsonify(result),200 if result.get("ok") else 502
