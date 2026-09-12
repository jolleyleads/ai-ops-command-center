import hashlib
import json

from flask import jsonify, request

from app import app, db, AutomationEvent, LeadPipeline, QualifiedLead
from universal_app import _search_public_records


def _clean(value, limit=300):
    return str(value or "").strip()[:limit]


def _permit_key(result):
    identity = "|".join([
        _clean(result.get("url"), 1000).lower(),
        _clean(result.get("contractor_name"), 200).lower(),
        _clean(result.get("location"), 200).lower(),
    ])
    return "permit-need-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:50]


@app.route("/api/permit-leads", methods=["POST"])
def permit_leads():
    data = request.get_json(silent=True) or {}
    location = _clean(data.get("location") or "", 200)
    user_query = _clean(data.get("query") or "master electrician permit pulling", 200)

    if not location:
        return jsonify({
            "configured": True,
            "message": "Enter a city/state location, for example: Portsmouth, VA.",
            "results": [],
        }), 400

    # Imported here so brave_app can finish loading all extension modules first.
    from verified_job_signals import _job_query_variants, _evaluate_item

    seen_urls = set()
    accepted = []
    rejected = []
    source_name = "Brave Search"

    for requested_source, query in _job_query_variants(location):
        payload = _search_public_records(query, "")
        source_name = payload.get("source") or source_name

        if not payload.get("configured"):
            return jsonify({
                "configured": False,
                "message": payload.get("message") or "Web search is not configured.",
                "results": [],
            }), 503

        for item in payload.get("results") or []:
            url = _clean(item.get("url"), 1200)
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            evaluated = _evaluate_item(item, requested_source, location)
            if not evaluated.get("accepted"):
                rejected.append(evaluated)
                continue

            company = _clean(evaluated.get("company"), 200)
            role_signals = evaluated.get("master_electrician_signals") or []
            permit_signals = evaluated.get("permit_pulling_signals") or []
            snippet = _clean(evaluated.get("source_snippet"), 1200)

            accepted.append({
                "type": "permit_lead",
                "title": company,
                "contractor_name": company,
                "subtitle": snippet,
                "url": evaluated.get("source_url") or "",
                "source": evaluated.get("source") or source_name,
                "location": location,
                "prospect_score": evaluated.get("prospect_score") or 0,
                "fit": "High",
                "lead_signal": "Contractor explicitly seeking a Master Electrician for permit-pulling or electrical-license qualifier responsibility.",
                "analysis": (
                    "Accepted only because the indexed source contains BOTH a Master Electrician signal "
                    "and an explicit permit-pulling/qualifier signal, and the company was uniquely verified "
                    "as a business in the requested location. Education, training, staffing, and generic electrician results are rejected."
                ),
                "master_electrician_signals": role_signals,
                "permit_pulling_signals": permit_signals,
                "phone": evaluated.get("phone") or "",
                "website": evaluated.get("website") or "",
                "business_address": evaluated.get("business_address") or "",
                "verified_business": True,
            })

    accepted.sort(key=lambda item: item.get("prospect_score", 0), reverse=True)

    return jsonify({
        "configured": True,
        "query": user_query,
        "location": location,
        "source": source_name,
        "precision_mode": "master_electrician_permit_pulling_only",
        "count": len(accepted),
        "rejected_count": len(rejected),
        "message": (
            f"Found {len(accepted)} verified contractor lead"
            + ("" if len(accepted) == 1 else "s")
            + " explicitly seeking a Master Electrician for permit-pulling/qualifier responsibility."
        ),
        "results": accepted,
    })


@app.route("/api/permit-leads/save", methods=["POST"])
def save_permit_lead():
    data = request.get_json(silent=True) or {}
    result = data.get("result") or {}
    if not isinstance(result, dict):
        return jsonify({"error": "result must be an object"}), 400

    if result.get("type") != "permit_lead" or not result.get("url") or not result.get("contractor_name"):
        return jsonify({"error": "A verified contractor lead with an evidence URL is required."}), 400

    key = _permit_key(result)
    lead = QualifiedLead.query.filter_by(workflow_run_id=key).first()
    lead_payload = {
        "name": _clean(result.get("contractor_name"), 200),
        "location": _clean(result.get("location"), 200),
        "phone": _clean(result.get("phone"), 100),
        "website": _clean(result.get("website"), 1000),
        "business_address": _clean(result.get("business_address"), 500),
        "evidence_url": _clean(result.get("url"), 1000),
        "source": _clean(result.get("source"), 200),
        "prospect_score": result.get("prospect_score"),
        "fit": _clean(result.get("fit"), 30),
        "master_electrician_signals": result.get("master_electrician_signals") or [],
        "permit_pulling_signals": result.get("permit_pulling_signals") or [],
    }
    ai_output = _clean(result.get("analysis"), 1500)

    try:
        if not lead:
            lead = QualifiedLead(
                workflow_run_id=key,
                lead=json.dumps(lead_payload, ensure_ascii=False),
                ai_output=ai_output,
                status="qualified",
                source="Master Electrician Permit-Pulling Lead",
            )
            db.session.add(lead)
            db.session.flush()
        else:
            lead.lead = json.dumps(lead_payload, ensure_ascii=False)
            lead.ai_output = ai_output
            lead.status = "qualified"
            lead.source = "Master Electrician Permit-Pulling Lead"

        pipeline = LeadPipeline.query.filter_by(qualified_lead_id=lead.id).first()
        if not pipeline:
            pipeline = LeadPipeline(
                qualified_lead_id=lead.id,
                stage="Qualified",
                notes="Saved from strict Master Electrician permit-pulling lead search. No outreach sent.",
                follow_up_date="",
            )
            db.session.add(pipeline)

        db.session.add(AutomationEvent(
            event_type="master_electrician_permit_lead_saved",
            source="Master Electrician Permit-Pulling Lead",
            status="success",
            details=f"lead_id={lead.id}; contractor={_clean(result.get('contractor_name'), 120)}",
        ))
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return jsonify({"error": f"Lead could not be saved: {_clean(exc, 250)}"}), 500

    return jsonify({"status": "saved", "qualified_lead_id": lead.id, "stage": "Qualified"})
