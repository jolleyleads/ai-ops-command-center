from pathlib import Path

def test_acceptance_runner_uses_company():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "company=marker" in text
