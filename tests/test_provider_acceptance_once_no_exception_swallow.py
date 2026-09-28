from pathlib import Path

def test_runner_does_not_swallow_exceptions():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "except Exception" not in text
