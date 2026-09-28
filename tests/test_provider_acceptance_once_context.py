from pathlib import Path

def test_runner_uses_app_context():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert "with app.app_context():" in source
