from pathlib import Path

def test_runner_has_no_direct_http_provider_calls():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "import requests" not in text
    assert "requests." not in text
