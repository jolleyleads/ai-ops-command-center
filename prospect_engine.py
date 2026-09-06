import hashlib
import json
import os

from flask import jsonify, request

from app import (
    app,
    db,
    AutomationEvent,
    LeadPipeline,
    QualifiedLead,
    openai_text,
)


def _clean(value, limit=500):
    return str(value or "").strip()[:limit]


def _evidence_score(result):
    score = 0
    evidence = []

    rating = result.get("rating")
    try:
        rating_value = float(rating) if rating is not None else None
    except (TypeError, ValueError):
        rating_value = None

    if rating_value is not None:
        if rating_value >= 4.5:
            score += 25
            evidence.append(f"Google rating {rating_value:.1f}")
        elif rating_value >= 4.0:
            score += 20
            evidence.append(f"Google rating {rating_value:.1f}")
        elif rating_value >= 3.5:
            score += 12
            evidence.append(f"Google rating {rating_value:.1f}")
        else:
            score += 5
            evidence.append(f"Google rating {rating_value:.1f}")

    reviews = result.get("review_count")
    try:
        review_count = int(reviews or 0)
    except (TypeError, ValueError):
        review_count = 0

    if review_count >= 100:
        score += 20
        evidence.append(f"{review_count} Google reviews")
    elif review_count >= 25:
        score += 15
        evidence.append(f"{review_count} Google reviews")
    elif review_count > 0:
        score += 8
        evidence.append(f"{review_count} Google reviews")

    if result.get("website"):
        score += 15
        evidence.append("website available")

    if result.get("phone"):
        score += 10
        evidence.append("public phone available")

    if result.get("subtitle"):
        score += 10
        evidence.append("location/address available")

    status = _clean(result.get("status"), 80).upper()
    if status == "OPERATIONAL":
        score += 10
        evidence.append("listed as operational")

    if result.get("id"):
        score += 5

    return min(score, 100), evidence


def _business_key(result):
    identity = "|".join(
        [
            _clean(result.get("id"), 300),
            _clean(result.get("title"), 300).lower(),
            _clean(result.get("subtitle"), 500).lower(),
        ]
    )
    return "prospect-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:55]


def _extract_json_array(text):
    if not text:
        return []

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.replace("```json", "", 1).replace("```", "", 1).strip()

    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start < 0 or end < start:
        return []

    try:
        parsed = json.loads(cleaned[start : end + 1])
    except (TypeError, ValueError):
        return []

    return parsed if isinstance(parsed, list) else []


def _ai_analyze(results, query, location):
    candidates = []
    by_id = {}

    for result in results[:12]:
        base_score, evidence = _evidence_score(result)
        item = {
            "id": _clean(result.get("id") or _business_key(result), 200),
            "title": _clean(result.get("title"), 300),
            "address": _clean(result.get("subtitle"), 500),
            "phone_present": bool(result.get("phone")),
            "website_present": bool(result.get("website")),
            "rating": result.get("rating"),
            "review_count": result.get("review_count"),
            "business_status": _clean(result.get("status"), 100),
            "deterministic_score": base_score,
            "evidence": evidence,
        }
        candidates.append(item)
        by_id[item["id"]] = item

    if not candidates or not os.environ.get("OPENAI_API_KEY"):
        return {}

    prompt = (
        "Analyze these business search results for fit as prospects for an automation/AI services company. "
        "Use ONLY the supplied fields. Do not invent an owner, email, revenue, company size, current software, "
        "buying intent, pain point, active project, or any other fact that is not in the evidence. "
        "Return ONLY a JSON array. For each item return: id, score, fit, reason, automation_opportunity. "
        "score must be an integer from 0 to 100 and should stay within 10 points of deterministic_score. "
        "fit must be one of high, medium, low. reason must cite only supplied evidence. "
        "automation_opportunity must be framed as a possible opportunity, not a claim about what the company currently needs. "
        f"Search query: {query}. Location: {location}. "
        "Candidates: " + json.dumps(candidates, ensure_ascii=False)
    )

    try:
        text, _ = openai_text(
            prompt,
            instructions="Be evidence-bound. Never infer missing facts. Output valid JSON only.",
        )
    except Exception:
        return {}

    parsed = _extract_json_array(text)
    output = {}

    for item in parsed:
        if not isinstance(item, dict):
            continue

        item_id = _clean(item.get("id"), 200)
        if item_id not in by_id:
            continue

        base = by_id[item_id]["deterministic_score"]

        try:
            ai_score = int(item.get("score"))
        except (TypeError, ValueError):
            ai_score = base

        ai_score = max(base - 10, min(base + 10, ai_score))
        ai_score = max(0, min(100, ai_score))

        fit = _clean(item.get("fit"), 20).lower()
        if fit not in {"high", "medium", "low"}:
            fit = "high" if ai_score >= 75 else "medium" if ai_score >= 55 else "low"

        output[item_id] = {
            "score": ai_score,
            "fit": fit,
            "reason": _clean(item.get("reason"), 800),
            "automation_opportunity": _clean(item.get("automation_opportunity"), 800),
            "analysis_source": "openai_evidence_bound",
        }

    return output


def _fallback_analysis(result):
    score, evidence = _evidence_score(result)
    fit = "high" if score >= 75 else "medium" if score >= 55 else "low"

    reason = "Evidence: " + ", ".join(evidence) if evidence else "Limited public evidence available."

    return {
        "score": score,
        "fit": fit,
        "reason": reason,
        "automation_opportunity": (
            "Possible opportunity: evaluate whether workflow automation, lead follow-up, "
            "or customer-response automation would be useful."
        ),
        "analysis_source": "rules_fallback",
    }


def _save_qualified(result, analysis, query, location):
    if analysis["score"] < 70:
        return None, False

    external_key = _business_key(result)
    lead = QualifiedLead.query.filter_by(workflow_run_id=external_key).first()

    lead_payload = {
        "name": _clean(result.get("title"), 300),
        "address": _clean(result.get("subtitle"), 500),
        "phone": _clean(result.get("phone"), 100),
        "website": _clean(result.get("website"), 1000),
        "google_maps_url": _clean(result.get("url"), 1000),
        "rating": result.get("rating"),
        "review_count": result.get("review_count"),
        "business_status": _clean(result.get("status"), 100),
        "search_query": _clean(query, 300),
        "search_location": _clean(location, 300),
        "prospect_score": analysis["score"],
        "fit": analysis["fit"],
    }

    ai_output = (
        f"Prospect score: {analysis['score']}/100\n"
        f"Fit: {analysis['fit']}\n"
        f"Reason: {analysis['reason']}\n"
        f"Possible automation opportunity: {analysis['automation_opportunity']}\n"
        f"Analysis source: {analysis['analysis_source']}"
    )

    created = False

    if not lead:
        lead = QualifiedLead(
            workflow_run_id=external_key,
            lead=json.dumps(lead_payload, ensure_ascii=False),
            ai_output=ai_output,
            status="qualified",
            source="Universal Business Prospecting",
        )
        db.session.add(lead)
        db.session.flush()
        created = True
    else:
        lead.lead = json.dumps(lead_payload, ensure_ascii=False)
        lead.ai_output = ai_output
        lead.status = "qualified"
        lead.source = "Universal Business Prospecting"

    pipeline = LeadPipeline.query.filter_by(qualified_lead_id=lead.id).first()
    if not pipeline:
        pipeline = LeadPipeline(
            qualified_lead_id=lead.id,
            stage="Qualified",
            notes="Auto-qualified from Universal Intelligence Search. No outreach sent.",
            follow_up_date="",
        )
        db.session.add(pipeline)
    elif pipeline.stage == "New":
        pipeline.stage = "Qualified"

    return lead, created


@app.route("/api/prospect-intake", methods=["POST"])
def prospect_intake():
    data = request.get_json(silent=True) or {}
    results = data.get("results") or []
    query = _clean(data.get("query"), 300)
    location = _clean(data.get("location"), 300)

    if not isinstance(results, list):
        return jsonify({"error": "results must be a list"}), 400

    businesses = [
        result
        for result in results[:20]
        if isinstance(result, dict) and result.get("type") == "business"
    ]

    ai_by_id = _ai_analyze(businesses, query, location)

    enriched = []
    saved_count = 0
    created_count = 0

    try:
        for result in businesses:
            result_id = _clean(result.get("id") or _business_key(result), 200)
            analysis = ai_by_id.get(result_id) or _fallback_analysis(result)

            lead, created = _save_qualified(result, analysis, query, location)
            if lead:
                saved_count += 1
                created_count += 1 if created else 0

            enriched.append(
                {
                    "id": result.get("id") or "",
                    "prospect_score": analysis["score"],
                    "fit": analysis["fit"],
                    "analysis": analysis["reason"],
                    "automation_opportunity": analysis["automation_opportunity"],
                    "analysis_source": analysis["analysis_source"],
                    "saved_to_pipeline": bool(lead),
                    "qualified_lead_id": lead.id if lead else None,
                }
            )

        db.session.add(
            AutomationEvent(
                event_type="prospect_intake",
                source="Universal Business Prospecting",
                status="success",
                details=(
                    f"query={query}; location={location}; "
                    f"analyzed={len(enriched)}; qualified={saved_count}; newly_saved={created_count}; "
                    "outreach_sent=0"
                ),
            )
        )
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return jsonify({"error": f"Prospect intake could not be saved: {_clean(exc, 300)}"}), 500

    return jsonify(
        {
            "status": "ok",
            "analyzed": len(enriched),
            "qualified": saved_count,
            "newly_saved": created_count,
            "outreach_sent": 0,
            "results": enriched,
            "note": (
                "Qualified prospects were staged in the existing lead pipeline. "
                "No email was sent because outreach has not been explicitly authorized for this campaign."
            ),
        }
    )
