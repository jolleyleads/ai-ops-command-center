from pathlib import Path

def test_acceptance_runner_does_not_hide_exceptions():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "except Exception" not in text
    assert "except:" not in text
