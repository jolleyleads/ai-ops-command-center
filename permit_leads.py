import hashlib
import json
import re
from datetime import datetime, timezone

from flask import jsonify, request

from app import app, db, AutomationEvent, LeadPipeline, QualifiedLead
from universal_app import _search_businesses, _search_public_records


def _clean(value, limit=300):
    return str(value or "").strip()[:limit]


def _location_parts(location):
    raw = _clean(location, 200)
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if len(parts) >= 2:
        return parts[0], parts[1]
    if len(parts) == 1:
        return parts[0], ""
    return "", ""


def _location_terms(location):
    raw = _clean(location, 200).lower()
    return [part.strip() for part in raw.split(",") if part.strip()]


def _strict_location_matches(title, snippet, location):
    terms = _location_terms(location)
    if not terms:
        return True
    text = f"{title} {snippet}".lower()
    return terms[0] in text


def _first_match(text, patterns, limit=160):
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = _clean(match.group(1), limit).strip(" .,:;-|")
            if value:
                return value
    return ""


def _extract_contractor_name(title, snippet):
    text = f"{title}\n{snippet}"
    return _first_match(
        text,
        [
            r"(?:electrical\s+)?contractor\s*(?:name)?\s*[:\-]\s*([^\n|;,]{3,100})",
            r"applicant\s*(?:name)?\s*[:\-]\s*([^\n|;,]{3,100})",
            r"trade\s+name\s*[:\-]\s*([^\n|;,]{3,100})",
            r"company\s*(?:name)?\s*[:\-]\s*([^\n|;,]{3,100})",
        ],
        100,
    )


def _extract_owner_name(title, snippet):
    text = f"{title}\n{snippet}"
    return _first_match(
        text,
        [
            r"(?:property\s+)?owner\s*(?:name)?\s*[:\-]\s*([^\n|;,]{3,120})",
            r"owner\s*[:\-]\s*([^\n|;,]{3,120})",
        ],
        120,
    )


def _extract_permit_number(title, snippet):
    text = f"{title} {snippet}"
    return _first_match(
        text,
        [
            r"permit\s*(?:#|no\.?|number)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-_/]{3,40})",
            r"\b(?:electrical|elec)\s+permit\s+([A-Z0-9][A-Z0-9\-_/]{3,40})",
        ],
        50,
    )


def _extract_date(title, snippet):
    text = f"{title} {snippet}"
    return _first_match(
        text,
        [
            r"\b((?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])/(?:20)\d{2})\b",
            r"\b((?:20)\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01]))\b",
            r"\b((?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},\s+20\d{2})\b",
        ],
        40,
    )


def _extract_address(title, snippet):
    text = f"{title}. {snippet}"
    return _first_match(
        text,
        [
            r"\b(\d{1,6}\s+[A-Z0-9][A-Z0-9 .'-]{2,80}\s+(?:Street|St|Road|Rd|Avenue|Ave|Boulevard|Blvd|Drive|Dr|Lane|Ln|Court|Ct|Circle|Cir|Way|Place|Pl|Parkway|Pkwy|Highway|Hwy)\.?)(?=\s|,|$)",
            r"(?:address|property|job\s+site|site)\s*[:\-]\s*([^\n|;]{5,140})",
        ],
        160,
    )


def _extract_project_type(title, snippet):
    text = f"{title} {snippet}".lower()
    labels = [
        ("EV charger", ("ev charger", "electric vehicle charger", "evse")),
        ("Electrical service upgrade", ("service upgrade", "service change", "service replacement")),
        ("Electrical panel", ("panel replacement", "panel upgrade", "electrical panel")),
        ("Generator", ("generator",)),
        ("Solar electrical", ("solar", "photovoltaic", "pv system")),
        ("Rewire", ("rewire", "rewiring")),
        ("New construction electrical", ("new construction",)),
        ("Electrical permit", ("electrical permit", "electrical work")),
    ]
    for label, terms in labels:
        if any(term in text for term in terms):
            return label
    return ""


def _has_active_permit_signal(title, snippet):
    text = f"{title} {snippet}".lower()
    return (
        "electrical" in text
        and "permit" in text
        and any(
            term in text
            for term in (
                "applied", "application", "submitted", "pending", "in progress",
                "issued", "permit #", "permit no", "applicant", "contractor", "trade name",
            )
        )
    )


def _score_result(title, snippet, location, year, contractor_name, enriched, permit_number, permit_date, address):
    text = f"{title} {snippet}".lower()
    score = 0
    if "electrical" in text and "permit" in text:
        score += 25
    if any(term in text for term in ("applied", "application", "submitted", "pending", "in progress", "issued")):
        score += 15
    if contractor_name:
        score += 20
    if str(year) in text:
        score += 10
    if _strict_location_matches(title, snippet, location):
        score += 10
    if permit_number:
        score += 5
    if permit_date:
        score += 5
    if address:
        score += 5
    if enriched:
        score += 5
    return min(score, 100)


def _enrich_contractor(contractor_name, location):
    if not contractor_name:
        return {}
    payload = _search_businesses(contractor_name, location)
    if not payload.get("configured") or not payload.get("results"):
        return {}
    target = contractor_name.lower()
    for business in payload.get("results", []):
        business_name = str(business.get("title") or "").lower()
        if target == business_name or target in business_name or business_name in target:
            return business
    return {}


def _permit_key(result):
    identity = "|".join([
        _clean(result.get("permit_number"), 80).lower(),
        _clean(result.get("url"), 1000).lower(),
        _clean(result.get("title"), 200).lower(),
        _clean(result.get("project_address"), 300).lower(),
    ])
    return "permit-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:55]


@app.route("/api/permit-leads", methods=["POST"])
def permit_leads():
    data = request.get_json(silent=True) or {}
    location = _clean(data.get("location") or "", 200)
    user_query = _clean(data.get("query") or "electrical permit activity", 200)

    if not location:
        return jsonify({"configured": True, "message": "Enter a city, state, or city/state in Location.", "results": []})

    year = datetime.now(timezone.utc).year
    city_or_state, state = _location_parts(location)
    location_phrase = ", ".join(part for part in [city_or_state, state] if part)
    targeted_queries = [
        f'"{location_phrase}" "electrical permit" contractor applicant submitted pending issued {year}',
        f'"{location_phrase}" "electrical permits" contractor applicant application issued {year}',
    ]

    seen = set()
    results = []
    source_name = "Public Record Search"

    for targeted_query in targeted_queries:
        payload = _search_public_records(targeted_query, "")
        source_name = payload.get("source") or source_name
        if not payload.get("configured"):
            return jsonify({"configured": False, "message": payload.get("message") or "Public-record search is not configured.", "results": []})
        if payload.get("message") and not payload.get("results"):
            return jsonify({"configured": True, "message": payload.get("message"), "source": source_name, "results": []})

        for item in payload.get("results", []):
            title = item.get("title") or "Permit activity"
            snippet = item.get("subtitle") or ""
            url = item.get("url") or ""
            if not url or url in seen:
                continue
            if not _strict_location_matches(title, snippet, location):
                continue
            if not _has_active_permit_signal(title, snippet):
                continue

            contractor_name = _extract_contractor_name(title, snippet)
            if not contractor_name:
                continue

            permit_number = _extract_permit_number(title, snippet)
            permit_date = _extract_date(title, snippet)
            project_address = _extract_address(title, snippet)
            owner_name = _extract_owner_name(title, snippet)
            project_type = _extract_project_type(title, snippet)
            enrichment = _enrich_contractor(contractor_name, location)
            seen.add(url)

            score = _score_result(
                title, snippet, location, year, contractor_name, bool(enrichment),
                permit_number, permit_date, project_address,
            )

            evidence = ["named contractor/applicant", "electrical permit language", f"location match: {location}"]
            if permit_number:
                evidence.append("permit number shown")
            if permit_date:
                evidence.append("permit date shown")
            if project_address:
                evidence.append("project address shown")

            results.append({
                "type": "permit_lead",
                "title": contractor_name,
                "subtitle": snippet,
                "url": url,
                "source": item.get("source") or source_name,
                "prospect_score": score,
                "fit": "High" if score >= 80 else "Medium" if score >= 65 else "Low",
                "lead_signal": f"Named contractor/applicant in {location} electrical-permit activity",
                "analysis": "Evidence used: " + ", ".join(evidence) + ". Missing fields are intentionally left blank.",
                "permit_number": permit_number,
                "permit_date": permit_date,
                "project_address": project_address,
                "project_type": project_type,
                "owner_name": owner_name,
                "contractor_name": contractor_name,
                "phone": enrichment.get("phone") or "",
                "website": enrichment.get("website") or "",
                "rating": enrichment.get("rating"),
                "review_count": enrichment.get("review_count"),
                "business_address": enrichment.get("subtitle") or "",
                "verified_business": bool(enrichment),
            })

    results.sort(key=lambda item: item.get("prospect_score", 0), reverse=True)
    return jsonify({
        "configured": True,
        "query": user_query,
        "location": location,
        "source": source_name,
        "count": len(results),
        "message": f"Found {len(results)} evidence-backed electrical permit lead" + ("" if len(results) == 1 else "s") + f" matching {location}.",
        "results": results,
    })


@app.route("/api/permit-leads/save", methods=["POST"])
def save_permit_lead():
    data = request.get_json(silent=True) or {}
    result = data.get("result") or {}
    if not isinstance(result, dict):
        return jsonify({"error": "result must be an object"}), 400

    if result.get("type") != "permit_lead" or not result.get("url") or not result.get("contractor_name"):
        return jsonify({"error": "A verified permit-lead result with contractor and evidence URL is required."}), 400

    key = _permit_key(result)
    lead = QualifiedLead.query.filter_by(workflow_run_id=key).first()
    lead_payload = {
        "name": _clean(result.get("contractor_name"), 200),
        "permit_number": _clean(result.get("permit_number"), 80),
        "permit_date": _clean(result.get("permit_date"), 50),
        "project_address": _clean(result.get("project_address"), 300),
        "project_type": _clean(result.get("project_type"), 120),
        "owner_name": _clean(result.get("owner_name"), 160),
        "phone": _clean(result.get("phone"), 100),
        "website": _clean(result.get("website"), 1000),
        "evidence_url": _clean(result.get("url"), 1000),
        "source": _clean(result.get("source"), 200),
        "prospect_score": result.get("prospect_score"),
        "fit": _clean(result.get("fit"), 30),
    }
    ai_output = _clean(result.get("analysis"), 1500)

    try:
        if not lead:
            lead = QualifiedLead(
                workflow_run_id=key,
                lead=json.dumps(lead_payload, ensure_ascii=False),
                ai_output=ai_output,
                status="qualified",
                source="Electrical Permit Lead",
            )
            db.session.add(lead)
            db.session.flush()
        else:
            lead.lead = json.dumps(lead_payload, ensure_ascii=False)
            lead.ai_output = ai_output
            lead.status = "qualified"
            lead.source = "Electrical Permit Lead"

        pipeline = LeadPipeline.query.filter_by(qualified_lead_id=lead.id).first()
        if not pipeline:
            pipeline = LeadPipeline(
                qualified_lead_id=lead.id,
                stage="Qualified",
                notes="Saved manually from evidence-backed electrical permit search. No outreach sent.",
                follow_up_date="",
            )
            db.session.add(pipeline)

        db.session.add(AutomationEvent(
            event_type="permit_lead_saved",
            source="Electrical Permit Lead",
            status="success",
            details=f"lead_id={lead.id}; contractor={_clean(result.get('contractor_name'), 120)}",
        ))
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return jsonify({"error": f"Permit lead could not be saved: {_clean(exc, 250)}"}), 500

    return jsonify({"status": "saved", "qualified_lead_id": lead.id, "stage": "Qualified"})
