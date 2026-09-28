from pathlib import Path

def test_acceptance_runner_remains_one_shot():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "while True" not in text
    assert "time.sleep" not in text
