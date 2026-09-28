from pathlib import Path

def test_runner_has_fail_function():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "def fail(reason):" in text
