import json

from prospect_app import app, Prospect
from app import openai_text


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
