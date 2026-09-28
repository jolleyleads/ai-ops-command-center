from pathlib import Path

def test_runner_has_no_background_loop():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert "while True" not in source
