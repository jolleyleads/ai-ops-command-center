from pathlib import Path

def test_acceptance_runner_does_not_add_routes():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "@app.route" not in text
