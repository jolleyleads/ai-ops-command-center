import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict

import requests
from flask import jsonify, request

from app import app, db, gmail_access_token, send_gmail
from src.services import run_ai

AUTO_SEND_MIN_SCORE = int(os.getenv("OUTREACH_AUTO_SEND_MIN_SCORE", "75"))
REVIEW_MIN_SCORE = int(os.getenv("OUTREACH_REVIEW_MIN_SCORE", "60"))
FIRST_FOLLOWUP_DAYS = int(os.getenv("OUTREACH_FIRST_FOLLOWUP_DAYS", "3"))
SECOND_FOLLOWUP_DAYS = int(os.getenv("OUTREACH_SECOND_FOLLOWUP_DAYS", "4"))
MAX_FOLLOWUPS = int(os.getenv("OUTREACH_MAX_FOLLOWUPS", "2"))


class OutreachLead(db.Model):
    __tablename__ = "outreach_lead"

    id = db.Column(db.Integer, primary_key=True)
    company = db.Column(db.String(300), nullable=False)
    contact_email = db.Column(db.String(500), default="")
    contact_name = db.Column(db.String(300), default="")
    location = db.Column(db.String(300), default="")
    source_url = db.Column(db.Text, default="")
    evidence_json = db.Column(db.Text, default="[]")
    score = db.Column(db.Integer, nullable=False, default=0)
    verification = db.Column(db.String(100), default="")
    status = db.Column(db.String(50), nullable=False, default="review")
    subject = db.Column(db.String(500), default="")
    body = db.Column(db.Text, default="")
    gmail_message_id = db.Column(db.String(255), default="")
    gmail_thread_id = db.Column(db.String(255), default="")
    sent_at = db.Column(db.DateTime)
    follow_up_due_at = db.Column(db.DateTime)
    follow_up_count = db.Column(db.Integer, nullable=False, default=0)
    replied_at = db.Column(db.DateTime)
    last_error = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


with app.app_context():
    db.create_all()


def _clean(value: Any, limit: int = 4000) -> str:
    return str(value or "").strip()[:limit]


def _serialize(lead: OutreachLead) -> Dict[str, Any]:
    try:
        evidence = json.loads(lead.evidence_json or "[]")
    except Exception:
        evidence = []

    return {
        "id": lead.id,
        "company": lead.company,
        "contact_email": lead.contact_email,
        "contact_name": lead.contact_name,
        "location": lead.location,
        "source_url": lead.source_url,
        "evidence": evidence,
        "score": lead.score,
        "verification": lead.verification,
        "status": lead.status,
        "subject": lead.subject,
        "body": lead.body,
        "gmail_message_id": lead.gmail_message_id,
        "gmail_thread_id": lead.gmail_thread_id,
        "sent_at": lead.sent_at.isoformat() if lead.sent_at else None,
        "follow_up_due_at": lead.follow_up_due_at.isoformat() if lead.follow_up_due_at else None,
        "follow_up_count": lead.follow_up_count,
        "replied_at": lead.replied_at.isoformat() if lead.replied_at else None,
        "last_error": lead.last_error,
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
    }


def _rank_status(score: int) -> str:
    if score >= AUTO_SEND_MIN_SCORE:
        return "qualified"
    if score >= REVIEW_MIN_SCORE:
        return "review"
    return "rejected"


def _draft_email(lead: OutreachLead, follow_up_number: int = 0) -> Dict[str, Any]:
    try:
        evidence = json.loads(lead.evidence_json or "[]")
    except Exception:
        evidence = []

    if follow_up_number:
        instructions = (
            "Write a concise B2B follow-up email. Use only facts in the supplied workflow data. "
            "Do not invent names, needs, credentials, dates, or claims. Return strict JSON with keys subject and body."
        )
        prompt = (
            f"Write follow-up #{follow_up_number} to {_clean(lead.company, 300)}. Keep the same subject when appropriate. "
            "Reference the prior outreach naturally, be professional, and ask for a simple reply or brief call. "
            "Do not claim they still need help unless the evidence says so."
        )
        workflow_data = {
            "company": lead.company,
            "location": lead.location,
            "evidence": evidence,
            "previous_subject": lead.subject,
            "previous_body": lead.body,
        }
    else:
        instructions = (
            "Write a concise personalized B2B outreach email for a verified contractor lead. "
            "Use only facts supplied in workflow data. Never invent a contact name, company need, license, project, or claim. "
            "Return strict JSON with keys subject and body."
        )
        prompt = (
            "Draft a short first-touch email offering Master Electrician / qualifying-agent / permit-pulling support only when "
            "the supplied evidence supports that need. Mention one specific verified signal, avoid hype, and end with a low-friction call to action."
        )
        workflow_data = {
            "company": lead.company,
            "location": lead.location,
            "score": lead.score,
            "verification": lead.verification,
            "evidence": evidence,
            "source_url": lead.source_url,
        }

    result = run_ai(
        prompt=f"{prompt}\n\nWORKFLOW DATA:\n{json.dumps(workflow_data, indent=2)}",
        instructions=instructions,
    )
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error") or "OpenAI drafting failed."}

    raw = _clean(result.get("output"), 8000)
    try:
        parsed = json.loads(raw)
    except Exception:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return {"ok": False, "error": "OpenAI did not return valid JSON."}
        try:
            parsed = json.loads(raw[start:end + 1])
        except Exception:
            return {"ok": False, "error": "OpenAI did not return valid JSON."}

    subject = _clean(parsed.get("subject"), 500)
    body = _clean(parsed.get("body"), 6000)
    if not subject or not body:
        return {"ok": False, "error": "OpenAI response was missing subject or body."}
    return {"ok": True, "subject": subject, "body": body, "model": result.get("model")}


def _gmail_send(to_email: str, subject: str, body: str, thread_id: str = "") -> Dict[str, Any]:
    try:
        if thread_id:
            from email.message import EmailMessage
            import base64

            token = gmail_access_token()
            msg = EmailMessage()
            msg["To"] = to_email
            msg["Subject"] = subject
            from_email = os.environ.get("GMAIL_FROM_EMAIL", "")
            if from_email:
                msg["From"] = from_email
            msg.set_content(body)
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode().rstrip("=")
            response = requests.post(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"raw": raw, "threadId": thread_id},
                timeout=30,
            )
            if not response.ok:
                return {"ok": False, "error": f"Gmail error {response.status_code}: {response.text[:500]}"}
            data = response.json()
        else:
            data = send_gmail(to_email, subject, body)

        return {
            "ok": True,
            "message_id": data.get("id"),
            "thread_id": data.get("threadId") or thread_id,
            "raw": data,
        }
    except Exception as exc:
        return {"ok": False, "error": _clean(exc, 1000)}


def _gmail_thread_has_reply(thread_id: str) -> Dict[str, Any]:
    try:
        token = gmail_access_token()
        response = requests.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{thread_id}",
            headers={"Authorization": f"Bearer {token}"},
            params={"format": "metadata", "metadataHeaders": ["From", "To"]},
            timeout=30,
        )
        if not response.ok:
            return {"ok": False, "replied": False, "error": f"Gmail thread lookup failed {response.status_code}: {response.text[:500]}"}
        data = response.json()
        messages = data.get("messages") or []
        if len(messages) <= 1:
            return {"ok": True, "replied": False, "raw": data}

        sender = (os.environ.get("GMAIL_FROM_EMAIL") or "").lower().strip()
        replied = False
        for message in messages[1:]:
            headers = {
                str(h.get("name") or "").lower(): str(h.get("value") or "")
                for h in ((message.get("payload") or {}).get("headers") or [])
            }
            from_value = headers.get("from", "").lower()
            if sender:
                if sender not in from_value:
                    replied = True
                    break
            else:
                replied = True
                break
        return {"ok": True, "replied": replied, "raw": data}
    except Exception as exc:
        return {"ok": False, "replied": False, "error": _clean(exc, 1000)}


@app.route("/api/outreach/leads", methods=["POST"])
def create_outreach_lead():
    data = request.get_json(silent=True) or {}
    company = _clean(data.get("company") or data.get("title") or data.get("name"), 300)
    if not company:
        return jsonify({"error": "company is required"}), 400

    try:
        score = int(data.get("score") if data.get("score") is not None else data.get("intent_score", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "score must be an integer"}), 400

    score = max(0, min(score, 100))
    evidence = data.get("evidence") if isinstance(data.get("evidence"), list) else []

    lead = OutreachLead(
        company=company,
        contact_email=_clean(data.get("contact_email") or data.get("email"), 500),
        contact_name=_clean(data.get("contact_name"), 300),
        location=_clean(data.get("location"), 300),
        source_url=_clean(data.get("source_url") or data.get("url") or data.get("website"), 1500),
        evidence_json=json.dumps(evidence),
        score=score,
        verification=_clean(data.get("verification"), 100),
        status=_rank_status(score),
    )
    db.session.add(lead)
    db.session.commit()
    return jsonify({"lead": _serialize(lead), "auto_send_eligible": lead.status == "qualified"}), 201


@app.route("/api/outreach/leads/<int:lead_id>/draft", methods=["POST"])
def draft_outreach(lead_id: int):
    lead = OutreachLead.query.get_or_404(lead_id)
    if lead.status == "rejected":
        return jsonify({"error": "lead is below the review threshold and cannot be auto-drafted"}), 409

    drafted = _draft_email(lead)
    if not drafted.get("ok"):
        lead.last_error = drafted.get("error") or "OpenAI drafting failed"
        lead.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify(drafted), 502

    lead.subject = drafted["subject"]
    lead.body = drafted["body"]
    lead.status = "drafted"
    lead.last_error = ""
    lead.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True, "lead": _serialize(lead), "model": drafted.get("model")})


@app.route("/api/outreach/leads/<int:lead_id>/send", methods=["POST"])
def send_outreach(lead_id: int):
    lead = OutreachLead.query.get_or_404(lead_id)
    if lead.score < AUTO_SEND_MIN_SCORE:
        return jsonify({"error": f"lead score must be at least {AUTO_SEND_MIN_SCORE} for automatic send"}), 409
    if not lead.contact_email:
        return jsonify({"error": "verified contact_email is required before send"}), 409

    if not lead.subject or not lead.body:
        drafted = _draft_email(lead)
        if not drafted.get("ok"):
            lead.last_error = drafted.get("error") or "OpenAI drafting failed"
            db.session.commit()
            return jsonify(drafted), 502
        lead.subject = drafted["subject"]
        lead.body = drafted["body"]

    sent = _gmail_send(lead.contact_email, lead.subject, lead.body)
    if not sent.get("ok"):
        lead.last_error = sent.get("error") or "Gmail send failed"
        lead.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify(sent), 502

    sent_at = datetime.utcnow()
    lead.gmail_message_id = _clean(sent.get("message_id"), 255)
    lead.gmail_thread_id = _clean(sent.get("thread_id"), 255)
    lead.sent_at = sent_at
    lead.follow_up_due_at = sent_at + timedelta(days=FIRST_FOLLOWUP_DAYS)
    lead.status = "sent"
    lead.last_error = ""
    lead.updated_at = sent_at
    db.session.commit()
    return jsonify({"ok": True, "lead": _serialize(lead)})


@app.route("/api/outreach/process-followups", methods=["POST"])
def process_followups():
    now = datetime.utcnow()
    leads = OutreachLead.query.filter(
        OutreachLead.status.in_(["sent", "followup_sent"]),
        OutreachLead.follow_up_due_at.isnot(None),
        OutreachLead.follow_up_due_at <= now,
        OutreachLead.replied_at.is_(None),
    ).all()

    processed = []
    for lead in leads:
        if not lead.gmail_thread_id:
            processed.append({"id": lead.id, "status": "skipped", "reason": "missing Gmail thread id"})
            continue

        reply = _gmail_thread_has_reply(lead.gmail_thread_id)
        if not reply.get("ok"):
            lead.last_error = reply.get("error") or "Gmail reply check failed"
            lead.updated_at = now
            processed.append({"id": lead.id, "status": "error", "error": lead.last_error})
            continue

        if reply.get("replied"):
            lead.status = "responded"
            lead.replied_at = now
            lead.follow_up_due_at = None
            lead.last_error = ""
            lead.updated_at = now
            processed.append({"id": lead.id, "status": "responded"})
            continue

        if lead.follow_up_count >= MAX_FOLLOWUPS:
            lead.status = "completed_no_reply"
            lead.follow_up_due_at = None
            lead.updated_at = now
            processed.append({"id": lead.id, "status": "completed_no_reply"})
            continue

        next_number = lead.follow_up_count + 1
        drafted = _draft_email(lead, follow_up_number=next_number)
        if not drafted.get("ok"):
            lead.last_error = drafted.get("error") or "OpenAI follow-up drafting failed"
            lead.updated_at = now
            processed.append({"id": lead.id, "status": "error", "error": lead.last_error})
            continue

        sent = _gmail_send(lead.contact_email, drafted["subject"], drafted["body"], lead.gmail_thread_id)
        if not sent.get("ok"):
            lead.last_error = sent.get("error") or "Gmail follow-up send failed"
            lead.updated_at = now
            processed.append({"id": lead.id, "status": "error", "error": lead.last_error})
            continue

        lead.subject = drafted["subject"]
        lead.body = drafted["body"]
        lead.gmail_message_id = _clean(sent.get("message_id"), 255)
        lead.gmail_thread_id = _clean(sent.get("thread_id") or lead.gmail_thread_id, 255)
        lead.follow_up_count = next_number
        lead.follow_up_due_at = now + timedelta(days=SECOND_FOLLOWUP_DAYS)
        lead.status = "followup_sent"
        lead.last_error = ""
        lead.updated_at = now
        processed.append({"id": lead.id, "status": "followup_sent", "follow_up_count": next_number})

    db.session.commit()
    return jsonify({"ok": True, "processed_count": len(processed), "processed": processed})


@app.route("/api/outreach/leads", methods=["GET"])
def list_outreach_leads():
    leads = OutreachLead.query.order_by(OutreachLead.id.desc()).limit(200).all()
    return jsonify({"leads": [_serialize(lead) for lead in leads]})
