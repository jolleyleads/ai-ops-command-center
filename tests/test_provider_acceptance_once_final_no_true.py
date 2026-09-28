from pathlib import Path

def test_acceptance_runner_does_not_hardcode_pass():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert '"ok": True' not in text
