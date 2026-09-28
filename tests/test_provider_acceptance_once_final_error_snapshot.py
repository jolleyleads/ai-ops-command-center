from pathlib import Path

def test_acceptance_snapshot_includes_error_state():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "last_error" in text
