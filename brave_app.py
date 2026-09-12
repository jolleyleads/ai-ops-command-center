import os

import requests

import universal_app as universal
from universal_app import app


def _brave_public_records(query, location=""):
    text_query = " ".join(part for part in [query, location] if part).strip()
    if not text_query:
        return {
            "configured": True,
            "source": "Brave Search",
            "message": "Enter a permit or public-record search.",
            "results": [],
        }

    brave_api_key = os.environ.get("BRAVE_SEARCH_API_KEY") or ""
    if not brave_api_key:
        return {
            "configured": False,
            "source": "Brave Search",
            "message": "Brave Search is not active in this running service. BRAVE_SEARCH_API_KEY is missing.",
            "results": [],
        }

    try:
        response = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": brave_api_key,
            },
            params={
                "q": text_query,
                "country": "US",
                "search_lang": "en",
                "count": 20,
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        return {
            "configured": True,
            "source": "Brave Search",
            "message": f"Brave Search request failed: {type(exc).__name__}.",
            "results": [],
        }

    if not response.ok:
        return {
            "configured": True,
            "source": "Brave Search",
            "message": f"Brave Search returned HTTP {response.status_code}.",
            "results": [],
        }

    return {
        "configured": True,
        "source": "Brave Search",
        "message": "",
        "results": universal._normalize_brave_search_results(response.json()),
    }


# Keep the existing app and routes intact; only replace the public-record
# provider used by universal_app.universal_search at request time.
universal._search_public_records = _brave_public_records
