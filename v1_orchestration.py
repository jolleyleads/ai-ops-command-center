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
from src.company_identity import owned_host, name_key, host, shared_host
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
    from src.execution_deadline import hard_stage_limit
    with hard_stage_limit(180,'contact_enrichment'):
        return _verified_public_email_impl(result)


def _verified_public_email_impl(result):
    """Return a source-observed or independently Hunter-verified company address.

    Third-party evidence may verify intent, but it can never establish the outreach recipient domain.
    """
    website = _clean(result.get("website"), 1800)
    if not website.startswith(("http://", "https://")):
        return "", ""
    company_urls = [website]

    # Search snippets and old stored emails are discovery hints, not current
    # contact proof. Always re-fetch the company pages before qualification.
    from src.execution_deadline import checkpoint
    checkpoint("fetching_contact_sources")
    contact_result = _public_contact_evidence(result)
    rows = contact_result[0] if isinstance(contact_result, tuple) else contact_result
    result['_outreach_copy_sources'] = [
        {'url': row.get('url'), 'page_text': str(row.get('page_text') or row.get('text') or '')[:4000],
         'directly_fetched': True, 'http_status': 200, 'source': 'outreach_primary_copy',
         'observed_at': row.get('observed_at')}
        for row in rows or [] if isinstance(row, dict) and row.get('company_identity')
        and row.get('directly_fetched') is True and row.get('http_status') == 200
        and owned_host(row.get('url', ''), website)
    ][:4]
    company=result.get("company") or result.get("name") or result.get("business_name") or result.get("candidate_name") or result.get("title")
    location=result.get("contact_location") or result.get("target_location") or result.get("location") or ""
    query=(result.get("_campaign_context") or {}).get("offer") or result.get("query") or result.get("business_need") or ""
    if query and not re.search(r'(?i)\b(?:hiring|jobs?|careers?)\b',query):query += " business outreach and follow-up automation"
    checkpoint("extracting_contacts")
    enrichment=enrich_lead({"company":company,"website":website,"target_location":location,"query":query},rows or [],email_allowed=_purpose_mailbox_allowed)
    from src.hunter_discovery import enrich_contact
    checkpoint("hunter_contact_lookup")
    contact_options={}
    if (result.get('_campaign_context') or {}).get('provider_contact_research') is True:contact_options['provider_people']=True
    enrich_contact(enrichment,website,required_person=(result.get('_campaign_context') or {}).get('require_decision_maker') is True,email_allowed=_purpose_mailbox_allowed,**contact_options)
    checkpoint("verifying_mailbox")
    apply_email_domain_check(enrichment)
    if (result.get('_campaign_context') or {}).get('require_decision_maker') is True:
        assessment=enrichment.get('contact_assessment') or {}
        from src.contact_assessment import person_email_supported
        if not person_email_supported(assessment,(enrichment.get('fields',{}).get('email') or {}).get('value')):
            if enrichment.get('fields',{}).get('email'):
                enrichment['fields']['email']['validated']=False
            assessment.setdefault('reason_codes',[]).append('NAMED_DECISION_MAKER_EMAIL_REQUIRED')
    result["_contact_enrichment"]=enrichment
    if (result.get('_campaign_context') or {}).get('prospect_policy')=='evidence-led-v1':
        from src.hunter_mailbox import verify_mailbox
        candidate=(enrichment.get('fields',{}).get('email') or {})
        if candidate.get('validated') and not (enrichment.get('contact_assessment') or {}).get('mailbox_validation'):
            enrichment.setdefault('contact_assessment',{})['mailbox_validation']=verify_mailbox(candidate['value'])
    validated=validated_payload(enrichment)
    email=_valid_email(validated.get("email"));url=_clean(validated.get("email_source_url"),1800)
    result["_contact_name"]=""
    if email and _purpose_mailbox_allowed(email) and _same_company_domain(email,company_urls) and owned_host(url,website):
        assessment=enrichment.get("contact_assessment") or {}
        from src.contact_assessment import person_email_supported
        if person_email_supported(assessment,email):
            result["_contact_name"]=validated.get("decision_maker") or ""
        source=next((row for row in rows or [] if row.get("url")==url),{})
        result["_contact_identity"]={"company_identity":source.get("company_identity") or {"company_name":company},"identity_version":"company-domain-v1","contact_location":location,"contact_assessment":assessment,"enrichment":enrichment,"outreach_copy_sources":result.get("_outreach_copy_sources") or []}
        return email,url
    return "",""


def _evidence_with_contact(result, email, email_source):
    observed = datetime.now(timezone.utc).isoformat()
    evidence = []
    evidence.extend(result.get('_prospect_sources') or [])
    for raw in _evidence_for_storage(result):
        if isinstance(raw, dict):
            item = dict(raw); item.setdefault("observed_at", observed); evidence.append(item)
    # Preserve fetched business facts independently of mailbox success. These
    # rows were admitted by the owned-host/company-identity fetch above; snippets
    # and untrusted contact hints are deliberately not promoted here.
    for row in result.get('_outreach_copy_sources') or []:
        if (isinstance(row,dict) and row.get('directly_fetched') is True
                and row.get('http_status')==200 and owned_host(row.get('url',''),result.get('website',''))):
            evidence.append(dict(row))
    if email and email_source:
        hunter=((result.get('_contact_enrichment') or {}).get('fields',{}).get('email') or {}).get('observation_status')=='hunter_discovered'
        evidence.append({"email": email, "url": email_source, "source": "hunter_verified_contact" if hunter else "verified_public_contact", "observed_at": observed,**(result.get("_contact_identity") or {})})
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
    context={"target_location": _clean(payload.get("location") or result.get("contact_location"), 300),"offer":_clean(payload.get("offer"),1200),
            "query": query, "intent_signal": query,
            "business_type": _clean(payload.get("business_type"), 300),
            "candidate_type": _clean(result.get("category") or result.get("type"), 300),
            "require_decision_maker": payload.get("require_decision_maker") is True or bool(re.search(r"(?i)\bdecision[ -]?makers?\b", query))}
    if payload.get('prospect_policy'):
        context.update(prospect_policy=payload['prospect_policy'],request_spec=payload.get('request_spec') or {},
                       discovery_sources=[_clean(result.get('source') or 'Unrecorded discovery source',120)])
    return context


def unfinished_lead_reasons(qualification,mailbox):
    # An opt-out mailbox receipt is informational: source-validated contacts
    # can still fail another qualification check and must recover that check.
    provider=[r for r in mailbox.get('reason_codes') or [] if r!='HUNTER_NOT_ENABLED']
    return provider or qualification.get('reason_codes') or ['CONTACT_EVIDENCE_MISSING']


def resume_discovery_lead(lead, result, lease_valid=None):
    """Refresh held discovery only, never rewrite a sent conversation."""
    from src.prospect_quality import POLICY, collect_sources
    context=result.get('_campaign_context') or {}
    if context.get('prospect_policy')==POLICY:
        result['_prospect_sources']=collect_sources(result,context)
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


def orchestrate_discovery(payload, *, authorized_send=False, draft_only=False):
    if not _outreach_search(payload):
        return {'enabled':False,'autosend_enabled':False,'paused_reason':'not_b2b_outreach_search','lead_ids':[],'eligible':0,'saved':0,'qualified':0,'drafted':0,'sent':0,'skipped':[]}
    from src.campaign_reporting import _active
    if os.getenv('AUTOMAKE_ISOLATED_EXECUTION')=='1' and _active.get():
        from src.progressive_campaign import run_business_tasks
        return run_business_tasks(payload,_active.get(),not draft_only and (AUTOSEND_ENABLED or authorized_send is True),int(payload.get('outreach_limit') or 0))
    return _orchestrate_discovery_serial(payload,authorized_send=authorized_send,draft_only=draft_only)


def _orchestrate_discovery_serial(payload, *, authorized_send=False, draft_only=False):
    send_enabled=not draft_only and (AUTOSEND_ENABLED or authorized_send is True)
    summary={"enabled":True,"autosend_enabled":send_enabled,"lead_ids":[],"eligible":0,"saved":0,"qualified":0,"drafted":0,"sent":0,"skipped":[],"contact_checks":[]}
    try: outreach_limit=max(0,int(payload.get("outreach_limit") or 0))
    except (TypeError,ValueError): outreach_limit=0
    if not _outreach_search(payload):
        summary["enabled"]=False; summary["paused_reason"]="not_b2b_outreach_search"; return summary
    for result in payload.get("results") or []:
        if outreach_limit and summary["sent"]>=outreach_limit: break
        if not isinstance(result,dict): continue
        company=_clean(result.get("company") or result.get("name") or result.get("business_name") or result.get("title"),300)
        score=_evidence_score(result)
        # An explicit selection can start evidence/contact work before discovery
        # ranking is complete. Qualification and sending still fail closed.
        selected=payload.get('_selected_workflow') is True
        # Draft-only research may inspect a discovered company's own site before
        # business/offer qualification is complete. The contact extractor still
        # requires freshly fetched company identity, and qualification below is
        # unchanged. A discovery label/score must not prevent that investigation.
        website=_clean(result.get('website'),1800)
        contact_research=(draft_only and result.get('classification')=='Candidate'
                          and website.startswith(('https://','http://'))
                          and bool(host(website)) and not shared_host(host(website)))
        if not company or (not selected and not contact_research and (score<QUEUE_MIN_SCORE or not _verified(result))): continue
        summary["eligible"]+=1
        urls=_candidate_urls(result); source_url=urls[0] if urls else ""
        if not source_url:
            summary["skipped"].append({"company":company,"reason":"missing_source_url"}); continue
        with discovery_lock(company,source_url) as acquired:
            if not acquired:
                summary['skipped'].append({'company':company,'reason':'discovery_in_progress'})
                continue
            existing_query=OutreachLead.query.filter_by(company=company,source_url=source_url)
            if selected:
                from workspace_security import scope
                existing_query=existing_query.filter(scope(OutreachLead,'lead',payload.get('_selected_workspace')))
            existing=existing_query.first()
            result={**result,"contact_location":payload.get("location") or result.get("contact_location") or result.get("location"),"query":payload.get("query") or payload.get("goal") or payload.get("intent_signal"),"_campaign_context":campaign_context(payload,result)}
            if existing:
                summary["lead_ids"].append(existing.id)
                from lead_recovery import LeadRecovery, schedule_recovery
                held = db.session.get(LeadRecovery, existing.id)
                if selected:
                    from outreach_automation import OutreachSendAttempt
                    safe_refresh=(existing.status in {'needs_evidence','qualified','drafted'}
                        and not existing.gmail_message_id and not existing.sent_at
                        and not OutreachSendAttempt.query.filter_by(lead_id=existing.id).first())
                    if safe_refresh and not (held and held.state=='running'):
                        refreshed=resume_discovery_lead(existing,result)
                        if refreshed.get('ok'):
                            summary['qualified']+=1;summary['drafted']+=1
                        else:
                            summary['skipped'].append({'company':company,'lead_id':existing.id,'reason':'verification_held',
                                                      'reason_codes':refreshed.get('reason_codes') or []})
                    continue
                # Reusing an unsent lead must not reuse eligibility for a different
                # offer. Preserve sent/uncertain conversations and active leases.
                from outreach_automation import OutreachSendAttempt, _server_qualification_inputs
                from src.prospect_quality import for_lead
                context=result['_campaign_context']
                if (context.get('prospect_policy')=='evidence-led-v1'
                        and existing.status in {'needs_evidence','qualified','drafted'}
                        and not existing.gmail_message_id and not existing.sent_at
                        and not OutreachSendAttempt.query.filter_by(lead_id=existing.id).first()
                        and not (held and held.state=='running')
                        and (_server_qualification_inputs(existing)[1]!=context or not for_lead(existing)['ready'])):
                    evidence=[r for r in json.loads(existing.evidence_json or '[]')
                              if isinstance(r,dict) and r.get('source')!='campaign_context']
                    evidence.append({'source':'campaign_context','context':context})
                    existing.evidence_json=json.dumps(evidence)
                    _store_qualification(existing)
                    held=schedule_recovery(existing,result,['PROSPECT_REASSESSMENT_REQUIRED'])
                if existing.status=='needs_evidence' and not existing.gmail_message_id and not held:
                    held=schedule_recovery(existing,result,['CONTACT_EVIDENCE_MISSING'])
                if held and existing.status in {'needs_evidence','qualified','drafted'}:
                    summary["skipped"].append({"company":company,"reason":"recovery_scheduled","lead_id":existing.id,"recovery_state":held.state})
                else:
                    summary["skipped"].append({"company":company,"reason":"already_queued","lead_id":existing.id})
                continue
            from src.execution_deadline import checkpoint
            checkpoint("enriching_contact")
            from src.prospect_quality import POLICY, collect_sources, assess
            if result['_campaign_context'].get('prospect_policy')==POLICY:
                result['_prospect_sources']=collect_sources(result,result['_campaign_context'])
                checkpoint('business_need_available',prospect_quality=assess(company,result.get('website') or '',result['_campaign_context'],result['_prospect_sources']))
            email,email_source=_verified_public_email(result)
            assessment=(result.get('_contact_enrichment') or {}).get('contact_assessment') or {}
            mailbox=assessment.get('mailbox_validation') or {}
            from src.contact_assessment import person_email_supported
            from src.mailbox_verification import current
            summary['contact_checks'].append({
                'company':company,'identity_status':(result.get('_contact_enrichment') or {}).get('identity_status','unproven'),
                'mailbox_verified':bool(email and current(mailbox,email)),
                'named_contact':bool(email and person_email_supported(assessment,email)),
                'checked_at':mailbox.get('checked_at'),
                'provider_reason_codes':list(dict.fromkeys(((assessment.get('hunter_discovery') or {}).get('reason_codes') or [])+(mailbox.get('reason_codes') or [])))})
            evidence=_evidence_with_contact(result,email,email_source)
            evidence.append({'source':'campaign_context','context':result['_campaign_context']})
            lead=OutreachLead(company=company,contact_email=email,contact_name=_clean(result.get("_contact_name"),300),location=_clean(result.get("location") or payload.get("location"),300),source_url=source_url,evidence_json=json.dumps(evidence),score=score,verification=_clean(result.get("verification"),100) or ("CANDIDATE" if contact_research else "SOURCE_VERIFIED"),status="needs_evidence")
            db.session.add(lead); db.session.flush();
            from src.campaign_reporting import attribute_new_lead
            attribute_new_lead(lead)
            if selected:
                from workspace_security import claim
                claim('lead',lead.id,payload['_selected_workspace'])
            db.session.commit(); summary["saved"]+=1; summary["lead_ids"].append(lead.id)
            qualification=_store_qualification(lead)
            if not qualification.get("ok"):
                from lead_recovery import schedule_recovery
                mailbox=(result.get('_contact_enrichment') or {}).get('contact_assessment',{}).get('mailbox_validation',{})
                schedule_recovery(lead,result,unfinished_lead_reasons(qualification,mailbox))
                assessment=(result.get('_contact_enrichment') or {}).get('contact_assessment') or {}
                provider_reasons=list(dict.fromkeys(((assessment.get('hunter_discovery') or {}).get('reason_codes') or [])+((assessment.get('mailbox_validation') or {}).get('reason_codes') or [])))
                summary["skipped"].append({"company":company,"lead_id":lead.id,"reason":"qualification_failed","reason_codes":qualification.get("reason_codes") or [],"provider_reason_codes":provider_reasons}); continue
            summary["qualified"]+=1
            if not email:
                summary["skipped"].append({"company":company,"lead_id":lead.id,"reason":"no_verified_public_email"}); continue
            checkpoint("drafting")
            drafted=_draft_email(lead)
            if not drafted.get("ok"):
                from lead_recovery import schedule_recovery
                schedule_recovery(lead,result,['DRAFT_FAILED'])
                lead.last_error=_clean(drafted.get("error"),2000); db.session.commit(); summary["skipped"].append({"company":company,"lead_id":lead.id,"reason":"draft_failed"}); continue
            lead.subject=drafted["subject"]; lead.body=drafted["body"]; lead.status="drafted"; lead.last_error=""; db.session.commit(); summary["drafted"]+=1
            if not send_enabled:
                summary["skipped"].append({"company":company,"lead_id":lead.id,"reason":"autosend_disabled","status":"drafted"}); continue
            if _send_prepared_lead(lead,summary):summary['sent']+=1
    return summary


def _send_prepared_lead(lead,summary):
    company=lead.company
    from src.execution_deadline import checkpoint
    checkpoint('sending')
    execution=_safe_send(lead,kind="initial",sequence=0,subject=lead.subject,body=lead.body)
    if not execution.get("ok"):
        lead.last_error=_clean(execution,2000); db.session.commit(); summary["skipped"].append({"company":company,"lead_id":lead.id,"reason":"safe_send_failed","stage":_clean(execution.get("stage"),100),"gate_reasons":((execution.get("gate") or {}).get("reasons") or []),"receipt_reasons":((execution.get("send_receipt") or {}).get("reasons") or []),"provider_error":_clean(execution.get("error"),500)}); return False
    receipt=execution.get("send_receipt") or {}; now=datetime.utcnow()
    lead.gmail_message_id=_clean(receipt.get("message_id"),255); lead.gmail_thread_id=_clean(receipt.get("thread_id"),255); lead.sent_at=now; lead.follow_up_due_at=now+timedelta(days=FIRST_FOLLOWUP_DAYS); lead.status="sent"; lead.last_error=""; lead.updated_at=now; db.session.commit()
    summary["skipped"].append({"company":company,"lead_id":lead.id,"status":"sent","message_id":lead.gmail_message_id,"thread_id":lead.gmail_thread_id})
    return True


def scan_real_inbound_replies():
    now=datetime.utcnow()
    # A saved status is display state, not proof that an authorized conversation
    # should stop being monitored. Recovery is limited to leads with an actual
    # successful initial-send receipt; an arbitrary typed email is not a grant.
    from outreach_automation import OutreachSendAttempt, gmail_access_token
    from src.outreach_safety import normalize_email
    import requests
    # Existing thread-bearing records remain readable for legacy inbox history.
    # Missing-thread recovery, however, requires a confirmed sent message.
    from sqlalchemy import or_, and_
    authorized_initial=and_(
        OutreachSendAttempt.kind == "initial",
        OutreachSendAttempt.status == "sent",
        OutreachSendAttempt.message_id.isnot(None),
        OutreachSendAttempt.message_id != "",
    )
    leads=OutreachLead.query.outerjoin(
        OutreachSendAttempt, OutreachSendAttempt.lead_id == OutreachLead.id
    ).filter(or_(
        and_(OutreachLead.gmail_thread_id.isnot(None), OutreachLead.gmail_thread_id != ""),
        authorized_initial,
    )).distinct().order_by(OutreachLead.id.asc()).all()
    processed=[]
    for lead in leads:
        if lead.status in {"opted_out","unsubscribed","archived","not_interested","rejected","closed"}:
            continue
        if not lead.gmail_thread_id:
            # Gmail's stable sent message ID resolves the provider thread even
            # after a partial receipt or process restart. Do not match on sender
            # alone: personal mail from this address may be unrelated.
            attempt=OutreachSendAttempt.query.filter_by(
                lead_id=lead.id, kind="initial", status="sent",
                recipient=normalize_email(lead.contact_email)
            ).filter(OutreachSendAttempt.message_id != "").order_by(
                OutreachSendAttempt.id.desc()
            ).first()
            if not attempt:
                processed.append({"lead_id":lead.id,"ok":False,"stage":"missing_authorized_send"})
                continue
            try:
                response=requests.get(
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{attempt.message_id}",
                    headers={"Authorization":f"Bearer {gmail_access_token()}"},
                    params={"format":"minimal"},timeout=30,
                )
                if not response.ok:
                    raise RuntimeError(f"GMAIL_MESSAGE_LOOKUP_{response.status_code}")
                thread_id=str((response.json() or {}).get("threadId") or "").strip()
                if not thread_id:
                    raise RuntimeError("GMAIL_THREAD_ID_NOT_FOUND")
                lead.gmail_thread_id=thread_id
                lead.gmail_message_id=lead.gmail_message_id or attempt.message_id
                db.session.commit()
            except Exception as exc:
                db.session.rollback()
                processed.append({"lead_id":lead.id,"ok":False,"stage":"thread_recovery_failed","reason":type(exc).__name__})
                continue
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
    if request.path!="/api/smart-search" or request.method != "POST" or response.status_code!=200 or not response.is_json: return response
    try:
        payload=response.get_json(silent=True) or {}; payload["outreach_automation"]=orchestrate_discovery(payload,draft_only=True); response.set_data(app.json.dumps(payload)); response.headers["Content-Type"]="application/json"; response.headers["Content-Length"]=str(len(response.get_data()))
    except Exception as exc: app.logger.exception("V1_DISCOVERY_ORCHESTRATION_ERROR %s",type(exc).__name__)
    return response


@app.route("/api/outreach/process-inbound",methods=["POST"])
def process_inbound_replies():
    import hmac
    expected=os.getenv("OUTREACH_CRON_TOKEN","").strip(); supplied=request.headers.get("X-Outreach-Cron-Token","")
    if not expected or not supplied or not hmac.compare_digest(expected,supplied): return jsonify({"ok":False,"error":"unauthorized"}),401
    result=scan_real_inbound_replies(); return jsonify(result),200 if result.get("ok") else 502
