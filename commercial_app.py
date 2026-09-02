import json
import re
from datetime import datetime

from prospect_app import app, db, Prospect
from app import openai_text


PIPELINE_STATUSES = ["new", "contacted", "qualified", "proposal sent", "won", "lost"]
OUTREACH_STATUSES = ["preview", "ready", "sent", "failed", "blocked"]
CONTACTED_OUTREACH_STATUSES = ["sent"]


class ProspectHistory(db.Model):
    __tablename__ = "prospect_history"

    id = db.Column(db.Integer, primary_key=True)
    prospect_id = db.Column(db.Integer, nullable=False, index=True)
    event_type = db.Column(db.String(50), nullable=False, index=True)
    from_status = db.Column(db.String(50), default="")
    to_status = db.Column(db.String(50), default="")
    note = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "prospect_id": self.prospect_id,
            "event_type": self.event_type,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "note": self.note,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class OutreachAttempt(db.Model):
    __tablename__ = "outreach_attempt"

    id = db.Column(db.Integer, primary_key=True)
    prospect_id = db.Column(db.Integer, nullable=False, index=True)
    company = db.Column(db.String(200), default="", nullable=False)
    company_normalized = db.Column(db.String(220), default="", nullable=False, index=True)
    recipient_email = db.Column(db.String(254), default="", nullable=False)
    email_normalized = db.Column(db.String(254), default="", nullable=False, index=True)
    subject = db.Column(db.Text, default="")
    body = db.Column(db.Text, default="")
    status = db.Column(db.String(30), default="preview", nullable=False, index=True)
    provider_message_id = db.Column(db.String(255), default="")
    openai_response_id = db.Column(db.String(255), default="")
    reason = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "prospect_id": self.prospect_id,
            "company": self.company,
            "recipient_email": self.recipient_email,
            "subject": self.subject,
            "body": self.body,
            "status": self.status,
            "provider_message_id": self.provider_message_id,
            "openai_response_id": self.openai_response_id,
            "reason": self.reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


def _list_value(value):
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _clean_note(value, max_len=2000):
    return str(value or "").strip()[:max_len]


def _normalize_email(value):
    return str(value or "").strip().lower()[:254]


def _normalize_company(value):
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:220]


def _contact_protection(prospect):
    email_normalized = _normalize_email(prospect.email)
    company_normalized = _normalize_company(prospect.company)

    query = OutreachAttempt.query.filter(
        OutreachAttempt.status.in_(CONTACTED_OUTREACH_STATUSES)
    )

    match = None
    match_type = ""
    if email_normalized:
        match = query.filter_by(email_normalized=email_normalized).order_by(
            OutreachAttempt.created_at.desc(), OutreachAttempt.id.desc()
        ).first()
        if match:
            match_type = "email"

    if not match and company_normalized:
        match = query.filter_by(company_normalized=company_normalized).order_by(
            OutreachAttempt.created_at.desc(), OutreachAttempt.id.desc()
        ).first()
        if match:
            match_type = "company"

    if match:
        return {
            "allowed": False,
            "blocked": True,
            "reason": f"duplicate contact protection: prior sent outreach matched by {match_type}",
            "match_type": match_type,
            "previous_attempt": match.to_dict(),
        }

    if not email_normalized:
        return {
            "allowed": False,
            "blocked": True,
            "reason": "recipient email is missing",
            "match_type": "missing_email",
            "previous_attempt": None,
        }

    return {
        "allowed": True,
        "blocked": False,
        "reason": "no prior sent outreach found for this company or email",
        "match_type": "",
        "previous_attempt": None,
    }


def _record_outreach_attempt(prospect, status, subject="", body="", response_id="", provider_message_id="", reason=""):
    row = OutreachAttempt(
        prospect_id=prospect.id,
        company=prospect.company or "",
        company_normalized=_normalize_company(prospect.company),
        recipient_email=prospect.email or "",
        email_normalized=_normalize_email(prospect.email),
        subject=subject or "",
        body=body or "",
        status=status,
        provider_message_id=provider_message_id or "",
        openai_response_id=response_id or "",
        reason=reason or "",
    )
    db.session.add(row)
    db.session.commit()
    return row


@app.route("/api/prospects/<int:prospect_id>/history", methods=["GET"])
def prospect_history_api(prospect_id):
    from flask import jsonify

    prospect = Prospect.query.get_or_404(prospect_id)
    rows = ProspectHistory.query.filter_by(prospect_id=prospect.id).order_by(
        ProspectHistory.created_at.desc(),
        ProspectHistory.id.desc(),
    ).all()

    return jsonify({
        "prospect_id": prospect.id,
        "current_status": prospect.status or "new",
        "count": len(rows),
        "history": [row.to_dict() for row in rows],
    })


@app.route("/api/prospects/<int:prospect_id>/pipeline", methods=["POST"])
def prospect_pipeline_update_api(prospect_id):
    from flask import request, jsonify

    prospect = Prospect.query.get_or_404(prospect_id)
    data = request.get_json(silent=True) or {}
    new_status = str(data.get("status") or "").strip().lower()
    note = _clean_note(data.get("note"))

    if new_status not in PIPELINE_STATUSES:
        return jsonify({
            "error": "invalid pipeline status",
            "allowed_statuses": PIPELINE_STATUSES,
        }), 400

    old_status = (prospect.status or "new").strip().lower()
    changed = new_status != old_status

    if changed:
        prospect.status = new_status
        db.session.add(ProspectHistory(
            prospect_id=prospect.id,
            event_type="status_change",
            from_status=old_status,
            to_status=new_status,
            note=note,
        ))
    elif note:
        db.session.add(ProspectHistory(
            prospect_id=prospect.id,
            event_type="note",
            from_status=old_status,
            to_status=old_status,
            note=note,
        ))

    db.session.commit()

    return jsonify({
        "status": "updated" if changed else "unchanged",
        "changed": changed,
        "prospect": prospect.to_dict(),
    })


@app.route("/api/prospects/<int:prospect_id>/notes", methods=["POST"])
def prospect_note_create_api(prospect_id):
    from flask import request, jsonify

    prospect = Prospect.query.get_or_404(prospect_id)
    data = request.get_json(silent=True) or {}
    note = _clean_note(data.get("note"))

    if not note:
        return jsonify({"error": "note is required"}), 400

    row = ProspectHistory(
        prospect_id=prospect.id,
        event_type="note",
        from_status=prospect.status or "new",
        to_status=prospect.status or "new",
        note=note,
    )
    db.session.add(row)
    db.session.commit()

    return jsonify({"status": "created", "history": row.to_dict()}), 201


@app.route("/api/prospects/<int:prospect_id>/outreach-history", methods=["GET"])
def prospect_outreach_history_api(prospect_id):
    from flask import jsonify

    prospect = Prospect.query.get_or_404(prospect_id)
    rows = OutreachAttempt.query.filter_by(prospect_id=prospect.id).order_by(
        OutreachAttempt.created_at.desc(), OutreachAttempt.id.desc()
    ).all()

    return jsonify({
        "prospect_id": prospect.id,
        "count": len(rows),
        "contact_protection": _contact_protection(prospect),
        "attempts": [row.to_dict() for row in rows],
    })


@app.route("/api/prospects/<int:prospect_id>/outreach-protection", methods=["GET"])
def prospect_outreach_protection_api(prospect_id):
    from flask import jsonify

    prospect = Prospect.query.get_or_404(prospect_id)
    result = _contact_protection(prospect)
    return jsonify({"prospect_id": prospect.id, **result})


@app.route("/api/prospects/<int:prospect_id>/outreach-attempts", methods=["POST"])
def prospect_outreach_attempt_create_api(prospect_id):
    """Audit/status recording only. This endpoint never sends email."""
    from flask import request, jsonify

    prospect = Prospect.query.get_or_404(prospect_id)
    data = request.get_json(silent=True) or {}
    status = str(data.get("status") or "").strip().lower()

    if status not in OUTREACH_STATUSES:
        return jsonify({
            "error": "invalid outreach status",
            "allowed_statuses": OUTREACH_STATUSES,
        }), 400

    if status == "sent":
        protection = _contact_protection(prospect)
        if protection["blocked"]:
            blocked = _record_outreach_attempt(
                prospect,
                "blocked",
                subject=str(data.get("subject") or "")[:500],
                reason=protection["reason"],
            )
            return jsonify({
                "status": "blocked",
                "sent": False,
                "contact_protection": protection,
                "attempt": blocked.to_dict(),
            }), 409

    row = _record_outreach_attempt(
        prospect,
        status,
        subject=str(data.get("subject") or "")[:500],
        body=str(data.get("body") or "")[:10000],
        provider_message_id=str(data.get("provider_message_id") or "")[:255],
        reason=str(data.get("reason") or "")[:2000],
    )

    return jsonify({
        "status": "recorded",
        "sent": False,
        "attempt": row.to_dict(),
        "contact_protection": _contact_protection(prospect),
        "note": "audit record only; this endpoint does not send email",
    }), 201


@app.route("/api/prospects/<int:prospect_id>/outreach-preview", methods=["POST"])
def prospect_outreach_preview_api(prospect_id):
    from flask import jsonify

    prospect = Prospect.query.get_or_404(prospect_id)
    data = prospect.to_dict()

    evidence = _list_value(data.get("evidence"))
    opportunities = _list_value(data.get("automation_opportunities"))

    prompt = f"""Write a short B2B outreach email body for this prospect.

Use ONLY the verified/provided facts below. Do not invent a contact name, problem, technology, staffing situation, or business need. If the evidence is thin, keep the wording general and factual.

Company: {data.get('company') or ''}
Industry: {data.get('industry') or ''}
City: {data.get('city') or ''}
State: {data.get('state') or ''}
Public rating: {data.get('google_rating') if data.get('google_rating') is not None else ''}
Public review count: {data.get('review_count') or 0}
Evidence: {json.dumps(evidence)}
Documented automation opportunities: {json.dumps(opportunities)}
Score: {data.get('score') or 0}/100
Score reason: {data.get('score_reason') or ''}

The sender offers business automation that can improve lead response, follow-up, qualification, booking, and repetitive office workflows when relevant.

Requirements:
- 70 to 120 words.
- Professional, natural, and specific to the verified facts.
- No fake compliments or unsupported claims.
- No pressure language.
- End with one simple call to action.
- Return only the email body.
"""

    try:
        body, response_id = openai_text(prompt)
    except RuntimeError as exc:
        _record_outreach_attempt(prospect, "failed", reason=str(exc)[:2000])
        return jsonify({"error": str(exc)}), 502
    except Exception:
        _record_outreach_attempt(prospect, "failed", reason="outreach preview generation failed")
        return jsonify({"error": "outreach preview generation failed"}), 502

    recipient_ready = bool(_normalize_email(data.get("email")))
    subject = f"Quick question for {prospect.company}"
    protection = _contact_protection(prospect)
    attempt = _record_outreach_attempt(
        prospect,
        "preview",
        subject=subject,
        body=body,
        response_id=response_id,
        reason="draft generated; no email sent",
    )

    return jsonify({
        "status": "preview",
        "prospect_id": prospect.id,
        "company": prospect.company,
        "subject": subject,
        "body": body,
        "recipient_email": data.get("email") or "",
        "recipient_ready": recipient_ready,
        "score": data.get("score") or 0,
        "score_band": data.get("score_band") or "poor",
        "openai_response_id": response_id,
        "outreach_attempt_id": attempt.id,
        "contact_protection": protection,
        "sent": False,
    })
