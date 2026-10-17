"""Offline tests: no provider calls, database, or outreach."""
import json
import os
import unittest
from unittest.mock import patch
from io import BytesIO
from live_discovery_app import app, discover

class LiveDiscoveryTests(unittest.TestCase):
    def test_missing_prompt(self):
        with patch.dict(os.environ, {"EXA_API_KEY": "test"}):
            body, code = discover("")
        self.assertEqual(code, 400)
        self.assertEqual(body["results"], [])

    def test_missing_provider_key(self):
        with patch.dict(os.environ, {}, clear=True):
            body, code = discover("Find 10 businesses")
        self.assertEqual(code, 503)
        self.assertEqual(body["provider_status"], "not_configured")

    def test_sources_are_unverified_and_deduplicated(self):
        payload = {"results": [
            {"title": "Example", "url": "https://example.org/"},
            {"title": "Duplicate", "url": "https://example.org/"},
            {"title": "Unsafe", "url": "http://example.net/"}
        ]}
        with patch.dict(os.environ, {"EXA_API_KEY": "test"}), patch(
            "live_discovery_app.urlopen", return_value=BytesIO(json.dumps(payload).encode())
        ):
            body, code = discover("Find companies", "United States", 10)
        self.assertEqual(code, 200)
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["verified_count"], 0)
        self.assertIn("unverified", body["results"][0]["classification"])

    def test_health_does_not_require_database(self):
        response = app.test_client().get("/api/live-discovery/health")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json["database_required"])

if __name__ == "__main__":
    unittest.main()
