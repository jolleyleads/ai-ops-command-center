from pathlib import Path

def test_runner_has_no_background_thread():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "threading" not in text
