import json
from datetime import datetime

from prospect_app import app, db, Prospect
from app import openai_text


PIPELINE_STATUSES = ["new", "contacted", "qualified", "proposal sent", "won", "lost"]


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
        return jsonify({"error": str(exc)}), 502
    except Exception:
        return jsonify({"error": "outreach preview generation failed"}), 502

    recipient_ready = bool((data.get("email") or "").strip())

    return jsonify({
        "status": "preview",
        "prospect_id": prospect.id,
        "company": prospect.company,
        "subject": f"Quick question for {prospect.company}",
        "body": body,
        "recipient_email": data.get("email") or "",
        "recipient_ready": recipient_ready,
        "score": data.get("score") or 0,
        "score_band": data.get("score_band") or "poor",
        "openai_response_id": response_id,
        "sent": False,
    })
