from pathlib import Path

def test_runner_captures_pre_cycle_snapshot():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "before = snapshot(lead)" in text
