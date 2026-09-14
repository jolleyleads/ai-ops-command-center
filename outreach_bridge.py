import os
import re
from urllib.parse import urlparse

import requests

from app import db
from gmail_outreach_state import already_contacted, gmail_ready, send_tracked_email
from outreach_automation import OutreachLead, _draft_email

EMAIL_RE = re.compile(r"(?i)(?<![\w.+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![\w.-])")
AUTO_SEND_MIN_SCORE = int(os.getenv("OUTREACH_AUTO_SEND_MIN_SCORE", "75"))
AUTOSEND_ENABLED = os.getenv("OUTREACH_AUTOSEND_ENABLED", "false").lower() in {"1", "true", "yes", "on"}


def _clean(value, limit=2000):
    return str(value or "").strip()[:limit]


def _valid_email(value):
    value = _clean(value, 500).lower()
    if not EMAIL_RE.fullmatch(value):
        return ""
    blocked_suffixes = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")
    if value.endswith(blocked_suffixes):
        return ""
    return value


def _same_company_domain(email, urls):
    domain = email.rsplit("@", 1)[-1].lower()
    for url in urls:
        try:
            host = (urlparse(url).hostname or "").lower()
        except Exception:
            continue
        if host.startswith("www."):
            host = host[4:]
        if domain == host or domain.endswith("." + host) or host.endswith("." + domain):
            return True
    return False


def _candidate_urls(result):
    urls = []
    for key in ("website", "direct_url", "source_url", "url"):
        value = _clean(result.get(key), 1800)
        if value.startswith(("http://", "https://")):
            urls.append(value)
    for evidence in result.get("evidence") or []:
        if isinstance(evidence, dict):
            value = _clean(evidence.get("url"), 1800)
            if value.startswith(("http://", "https://")):
                urls.append(value)
    seen = set()
    out = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out[:4]


def _verified_public_email(result):
    urls = _candidate_urls(result)

    for key in ("contact_email", "email", "recruiterEmail"):
        email = _valid_email(result.get(key))
        if email and (not urls or _same_company_domain(email, urls)):
            return email, "search_result"

    for evidence in result.get("evidence") or []:
        if not isinstance(evidence, dict):
            continue
        for value in evidence.values():
            if not isinstance(value, str):
                continue
            for candidate in EMAIL_RE.findall(value):
                email = _valid_email(candidate)
                if email and (not urls or _same_company_domain(email, urls)):
                    return email, "evidence"

    headers = {"User-Agent": "Mozilla/5.0 AI-Ops-Contact-Verification/1.0"}
    for url in urls:
        try:
            response = requests.get(url, headers=headers, timeout=8, allow_redirects=True)
        except requests.RequestException:
            continue
        if not response.ok:
            continue
        content_type = (response.headers.get("content-type") or "").lower()
        if "text/html" not in content_type and "text/plain" not in content_type:
            continue
        text = response.text[:500000]
        for candidate in EMAIL_RE.findall(text):
            email = _valid_email(candidate)
            if email and _same_company_domain(email, [response.url, url]):
                return email, response.url

    return "", ""


def _lead_score(result):
    raw = result.get("intent_score")
    if raw is None:
        raw = result.get("prospect_score")
    if raw is None:
        raw = result.get("quality_score")
    try:
        return max(0, min(int(raw), 100))
    except (TypeError, ValueError):
        return 0


def _verified_intent(result):
    label = _clean(result.get("verification"), 100).upper()
    return label in {
        "VERIFIED_INTENT",
        "CROSS_CHECKED_VERIFIED_INTENT",
        "LIKELY_VERIFIED_INTENT",
        "VERIFIED",
    }


def ingest_verified_results(search_payload):
    summary = {"enabled": AUTOSEND_ENABLED, "eligible": 0, "saved": 0, "sent": 0, "skipped": []}
    if not AUTOSEND_ENABLED:
        return summary

    gmail_status = gmail_ready()
    if not gmail_status.get("ok"):
        summary["enabled"] = False
        summary["paused_reason"] = gmail_status.get("reason") or "gmail_not_ready"
        return summary

    intent = _clean(search_payload.get("intent"), 100)
    if intent not in {"contractors", "permit_leads"}:
        return summary

    for result in search_payload.get("results") or []:
        if not isinstance(result, dict):
            continue
        company = _clean(result.get("company") or result.get("name") or result.get("title"), 300)
        score = _lead_score(result)
        if not company or score < AUTO_SEND_MIN_SCORE or not _verified_intent(result):
            continue

        summary["eligible"] += 1
        source_url = _clean(result.get("source_url") or result.get("website") or result.get("url"), 1800)

        email, email_source = _verified_public_email(result)
        if not email:
            summary["skipped"].append({"company": company, "reason": "no_verified_public_email"})
            continue

        if already_contacted(email):
            summary["skipped"].append({"company": company, "reason": "already_contacted_gmail"})
            continue

        existing = OutreachLead.query.filter_by(company=company).filter(
            OutreachLead.status.in_(["sent", "followup_sent", "responded", "completed_no_reply"])
        ).first()
        if existing:
            summary["skipped"].append({"company": company, "reason": "already_contacted_local"})
            continue

        lead = OutreachLead(
            company=company,
            contact_email=email,
            location=_clean(result.get("location") or search_payload.get("location"), 300),
            source_url=source_url,
            evidence_json=__import__("json").dumps(result.get("evidence") or []),
            score=score,
            verification=_clean(result.get("verification"), 100),
            status="qualified",
        )
        db.session.add(lead)
        db.session.commit()
        summary["saved"] += 1

        drafted = _draft_email(lead)
        if not drafted.get("ok"):
            lead.last_error = _clean(drafted.get("error"), 2000)
            db.session.commit()
            summary["skipped"].append({"company": company, "reason": "draft_failed"})
            continue

        lead.subject = drafted["subject"]
        lead.body = drafted["body"]
        sent = send_tracked_email(email, lead.subject, lead.body, company, step="initial")
        if not sent.get("ok"):
            lead.last_error = _clean(sent.get("error"), 2000)
            db.session.commit()
            summary["skipped"].append({"company": company, "reason": "gmail_send_failed"})
            continue

        from datetime import datetime, timedelta
        sent_at = datetime.utcnow()
        lead.gmail_message_id = _clean(sent.get("message_id"), 255)
        lead.gmail_thread_id = _clean(sent.get("thread_id"), 255)
        lead.sent_at = sent_at
        lead.follow_up_due_at = sent_at + timedelta(days=int(os.getenv("OUTREACH_FIRST_FOLLOWUP_DAYS", "3")))
        lead.status = "sent"
        lead.last_error = ""
        db.session.commit()
        summary["sent"] += 1
        summary["skipped"].append({"company": company, "email_source": email_source, "status": "sent"})

    return summary
