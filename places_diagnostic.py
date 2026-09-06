import os

import requests
from flask import jsonify, request

from app import app


def _clean(value, limit=500):
    return str(value or "").strip()[:limit]


def _google_error(payload):
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return {
            "code": error.get("code"),
            "status": error.get("status"),
            "message": _clean(error.get("message"), 1000),
        }
    return {"code": None, "status": "", "message": ""}


@app.route("/api/places-diagnostic")
def places_diagnostic():
    api_key = (
        os.environ.get("GOOGLE_PLACES_API_KEY")
        or os.environ.get("GOOGLE_MAPS_API_KEY")
        or ""
    )

    if not api_key:
        return jsonify({
            "ok": False,
            "configured": False,
            "message": "GOOGLE_PLACES_API_KEY is not available to this Render service.",
        }), 500

    query = _clean(request.args.get("query") or "electrical contractors", 300)
    location = _clean(request.args.get("location") or "Portsmouth, VA", 200)
    text_query = " ".join(part for part in [query, location] if part).strip()

    try:
        response = requests.post(
            "https://places.googleapis.com/v1/places:searchText",
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": "places.id,places.displayName",
            },
            json={"textQuery": text_query, "maxResultCount": 1},
            timeout=20,
        )
    except requests.RequestException as exc:
        return jsonify({
            "ok": False,
            "configured": True,
            "message": f"Places connection error: {_clean(exc, 500)}",
        }), 502

    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if response.ok:
        places = payload.get("places") or []
        return jsonify({
            "ok": True,
            "configured": True,
            "http_status": response.status_code,
            "message": "Google Places request succeeded with the Render key.",
            "result_count": len(places),
        })

    detail = _google_error(payload)
    return jsonify({
        "ok": False,
        "configured": True,
        "http_status": response.status_code,
        "google_error_code": detail["code"],
        "google_error_status": detail["status"],
        "google_error_message": detail["message"],
        "message": "Google Places rejected the request. The API key value is not exposed by this diagnostic.",
    }), response.status_code
