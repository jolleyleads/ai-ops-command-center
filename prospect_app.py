import json

from app import app, db
from prospect_engine import register_prospect_model, apply_score, score_prospect


Prospect = register_prospect_model(db)


def _json_text_list(value):
    if value is None:
        return "[]"
    if isinstance(value, list):
        return json.dumps(value)
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return "[]"
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return json.dumps(parsed)
        except Exception:
            pass
        return json.dumps([value])
    return json.dumps([str(value)])


def _clean_text(value, max_len=None):
    text = "" if value is None else str(value).strip()
    if max_len is not None:
        text = text[:max_len]
    return text


def _safe_int(value, default=0, minimum=None):
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    if minimum is not None:
        result = max(minimum, result)
    return result


def _safe_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool_value(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {
        "1", "true", "yes", "y", "on"
    }


def _prospect_from_payload(data):
    company = _clean_text(data.get("company"), 200)
    if not company:
        raise ValueError("company is required")

    prospect = Prospect(
        company=company,
        website=_clean_text(data.get("website")),
        email=_clean_text(data.get("email"), 254),
        phone=_clean_text(data.get("phone"), 50),
        contact_name=_clean_text(data.get("contact_name"), 200),
        contact_title=_clean_text(data.get("contact_title"), 160),
        source=_clean_text(data.get("source"), 120),
        source_url=_clean_text(data.get("source_url")),
        city=_clean_text(data.get("city"), 120),
        state=_clean_text(data.get("state"), 80),
        industry=_clean_text(data.get("industry"), 120),
        hiring_signal=_bool_value(data.get("hiring_signal")),
        hiring_roles=_json_text_list(data.get("hiring_roles")),
        review_count=_safe_int(data.get("review_count"), 0, 0),
        google_rating=_safe_float(data.get("google_rating")),
        locations_count=_safe_int(data.get("locations_count"), 1, 1),
        high_lead_volume_signal=_bool_value(data.get("high_lead_volume_signal")),
        manual_followup_signal=_bool_value(data.get("manual_followup_signal")),
        crm_need_signal=_bool_value(data.get("crm_need_signal")),
        growth_signal=_bool_value(data.get("growth_signal")),
        automation_opportunities=_json_text_list(data.get("automation_opportunities")),
        evidence=_json_text_list(data.get("evidence")),
        status=_clean_text(data.get("status"), 50) or "new",
    )
    apply_score(prospect)
    return prospect


@app.route("/api/prospects", methods=["GET", "POST"])
def prospects_api():
    if app.request_class is None:
        return {"error": "request system unavailable"}, 500

    from flask import request, jsonify

    if request.method == "GET":
        limit = _safe_int(request.args.get("limit"), 100, 1)
        limit = min(limit, 500)
        min_score = _safe_int(request.args.get("min_score"), 0, 0)
        band = _clean_text(request.args.get("band"), 30).lower()

        query = Prospect.query.filter(Prospect.score >= min_score)
        if band:
            query = query.filter(Prospect.score_band == band)

        rows = query.order_by(
            Prospect.score.desc(),
            Prospect.updated_at.desc(),
        ).limit(limit).all()

        return jsonify({
            "count": len(rows),
            "prospects": [row.to_dict() for row in rows],
        })

    data = request.get_json(silent=True) or {}
    try:
        prospect = _prospect_from_payload(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    db.session.add(prospect)
    db.session.commit()

    return jsonify({
        "status": "created",
        "prospect": prospect.to_dict(),
    }), 201


@app.route("/api/prospects/<int:prospect_id>", methods=["GET", "PATCH", "DELETE"])
def prospect_detail_api(prospect_id):
    from flask import request, jsonify

    prospect = Prospect.query.get_or_404(prospect_id)

    if request.method == "GET":
        return jsonify(prospect.to_dict())

    if request.method == "DELETE":
        db.session.delete(prospect)
        db.session.commit()
        return jsonify({"status": "deleted", "id": prospect_id})

    data = request.get_json(silent=True) or {}

    text_fields = {
        "company": 200,
        "website": None,
        "email": 254,
        "phone": 50,
        "contact_name": 200,
        "contact_title": 160,
        "source": 120,
        "source_url": None,
        "city": 120,
        "state": 80,
        "industry": 120,
        "status": 50,
    }
    for field, max_len in text_fields.items():
        if field in data:
            setattr(prospect, field, _clean_text(data.get(field), max_len))

    if not prospect.company:
        return jsonify({"error": "company is required"}), 400

    bool_fields = [
        "hiring_signal",
        "high_lead_volume_signal",
        "manual_followup_signal",
        "crm_need_signal",
        "growth_signal",
    ]
    for field in bool_fields:
        if field in data:
            setattr(prospect, field, _bool_value(data.get(field)))

    if "review_count" in data:
        prospect.review_count = _safe_int(data.get("review_count"), 0, 0)
    if "locations_count" in data:
        prospect.locations_count = _safe_int(data.get("locations_count"), 1, 1)
    if "google_rating" in data:
        prospect.google_rating = _safe_float(data.get("google_rating"))

    for field in ["hiring_roles", "automation_opportunities", "evidence"]:
        if field in data:
            setattr(prospect, field, _json_text_list(data.get(field)))

    apply_score(prospect)
    db.session.commit()

    return jsonify({
        "status": "updated",
        "prospect": prospect.to_dict(),
    })


@app.route("/api/prospects/score", methods=["POST"])
def prospect_score_preview_api():
    from flask import request, jsonify

    data = request.get_json(silent=True) or {}
    return jsonify(score_prospect(data))


@app.route("/api/prospects/<int:prospect_id>/rescore", methods=["POST"])
def prospect_rescore_api(prospect_id):
    from flask import jsonify

    prospect = Prospect.query.get_or_404(prospect_id)
    result = apply_score(prospect)
    db.session.commit()

    return jsonify({
        "status": "rescored",
        "result": result,
        "prospect": prospect.to_dict(),
    })


@app.route("/api/prospects/hot", methods=["GET"])
def hot_prospects_api():
    from flask import request, jsonify

    limit = min(_safe_int(request.args.get("limit"), 50, 1), 200)
    rows = Prospect.query.filter(
        Prospect.score >= 80
    ).order_by(
        Prospect.score.desc(),
        Prospect.updated_at.desc(),
    ).limit(limit).all()

    return jsonify({
        "count": len(rows),
        "threshold": 80,
        "prospects": [row.to_dict() for row in rows],
    })


@app.route("/api/prospects/health", methods=["GET"])
def prospect_health_api():
    from flask import jsonify

    try:
        db.session.execute(db.text("SELECT 1"))
        database_ok = True
    except Exception:
        db.session.rollback()
        database_ok = False

    return jsonify({
        "status": "ok" if database_ok else "degraded",
        "prospect_engine": True,
        "database": database_ok,
        "qualification_threshold": 80,
    }), 200 if database_ok else 503
