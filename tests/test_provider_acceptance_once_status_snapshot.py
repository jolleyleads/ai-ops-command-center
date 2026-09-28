from pathlib import Path

def test_snapshot_contains_status():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert '"status": lead.status' in source
