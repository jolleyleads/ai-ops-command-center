from pathlib import Path

def test_runner_has_snapshot_helper():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "def snapshot(lead):" in text
