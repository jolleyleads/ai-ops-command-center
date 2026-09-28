from pathlib import Path

def test_runner_has_no_bare_except():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "except:" not in text
