from pathlib import Path

def test_runner_adds_no_http_routes():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "@app.route" not in text
