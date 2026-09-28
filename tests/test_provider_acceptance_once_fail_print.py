from pathlib import Path

def test_runner_prints_failure_payload():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "def fail(reason):" in text
    assert "PROVIDER_ACCEPTANCE_RESULT" in text
