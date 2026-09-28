from pathlib import Path

def test_runner_has_no_internal_retry_loop():
    text = Path("scripts/provider_acceptance_once.py").read_text().lower()
    assert "retry" not in text
