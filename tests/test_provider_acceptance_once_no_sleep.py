from pathlib import Path

def test_runner_has_no_sleep_or_poll_loop():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "time.sleep" not in text
