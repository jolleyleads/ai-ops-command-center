from pathlib import Path

def test_acceptance_snapshot_includes_status():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "lead.status" in text
