import json
import os
import re
from datetime import datetime, timedelta, timezone
from flask import jsonify, request
from app import app, db
from outreach_bridge import QUEUE_MIN_SCORE, _candidate_urls, _clean, _outreach_search, _evidence_for_storage, _evidence_score, _public_contact_evidence, _same_company_domain, _valid_email, _verified
from outreach_automation import FIRST_FOLLOWUP_DAYS, OutreachLead, _draft_email, _gmail_thread_reply_state, _persist_reply_evidence, _route_persisted_reply, _safe_send, _store_qualification

AUTOSEND_ENABLED = os.getenv("OUTREACH_AUTOSEND_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
EMAIL_SCAN_RE = re.compile(r"(?i)(?<![\w.+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![\w.-])")


def _verified_public_email(result):
    """Return only a source-visible email on the prospect's explicit company website domain.

    Third-party evidence may verify intent, but it can never establish the outreach recipient domain.
    """
    website = _clean(result.get("website"), 1800)
    if not website.startswith(("http://", "https://")):
        return "", ""
    company_urls = [website]

    direct_rows = [result]
    direct_rows.extend(x for x in (result.get("evidence") or []) if isinstance(x, dict))
    for row in direct_rows:
        row_url = _clean(row.get("url") or row.get("source_url") or row.get("website") or row.get("verification_source_url"), 1800)
        text = " ".join([_clean(row.get("email"), 500), _clean(row.get("subtitle"), 5000), _clean(row.get("snippet"), 5000), _clean(row.get("text"), 120000)])
        for raw in EMAIL_SCAN_RE.findall(text):
            email = _valid_email(raw)
            if email and _same_company_domain(email, company_urls):
                return email, row_url or website

    contact_result = _public_contact_evidence(result)
    rows = contact_result[0] if isinstance(contact_result, tuple) else contact_result
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        url = _clean(row.get("url"), 1800)
        text = " ".join([_clean(row.get("subtitle"), 5000), _clean(row.get("text"), 120000)])
        for raw in EMAIL_SCAN_RE.findall(text):
            email = _valid_email(raw)
            if email and _same_company_domain(email, company_urls):
                return email, url
    return "", ""


def _evidence_with_contact(result, email, email_source):
    observed = datetime.now(timezone.utc).isoformat()
    evidence = []
    for raw in _evidence_for_storage(result):
        if isinstance(raw, dict):
            item = dict(raw); item.setdefault("observed_at", observed); evidence.append(item)
    if email and email_source:
        evidence.append({"email": email, "url": email_source, "source": "verified_public_contact", "observed_at": observed})
    return evidence


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
        existing=OutreachLead.query.filter_by(company=company,source_url=source_url).first()
        if existing:
            summary["skipped"].append({"company":company,"reason":"already_queued","lead_id":existing.id}); continue
        email,email_source=_verified_public_email(result)
        evidence=_evidence_with_contact(result,email,email_source)
        lead=OutreachLead(company=company,contact_email=email,contact_name=_clean(result.get("contact_name"),300),location=_clean(result.get("location") or payload.get("location"),300),source_url=source_url,evidence_json=json.dumps(evidence),score=score,verification=_clean(result.get("verification"),100) or "SOURCE_VERIFIED",status="needs_evidence")
        db.session.add(lead); db.session.commit(); summary["saved"]+=1
        qualification=_store_qualification(lead)
        if not qualification.get("ok"):
            summary["skipped"].append({"company":company,"lead_id":lead.id,"reason":"qualification_failed","reason_codes":qualification.get("reason_codes") or []}); continue
        summary["qualified"]+=1
        if not email:
            summary["skipped"].append({"company":company,"lead_id":lead.id,"reason":"no_verified_public_email"}); continue
        drafted=_draft_email(lead)
        if not drafted.get("ok"):
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
    leads=OutreachLead.query.filter(OutreachLead.gmail_thread_id.isnot(None),OutreachLead.gmail_thread_id!="",OutreachLead.replied_at.is_(None),OutreachLead.status.in_(["sent","followup_sent"])).order_by(OutreachLead.id.asc()).all()
    processed=[]
    for lead in leads:
        reply=_gmail_thread_reply_state(lead.gmail_thread_id)
        if not reply.get("ok"):
            processed.append({"lead_id":lead.id,"ok":False,"stage":"reply_check_failed","reason":reply.get("reason"),"error":reply.get("error")}); continue
        if not reply.get("replied"):
            processed.append({"lead_id":lead.id,"ok":True,"stage":"no_reply"}); continue
        _persist_reply_evidence(lead,reply); routed=_route_persisted_reply(lead,reply,now); lead.updated_at=now; db.session.commit()
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
