from pathlib import Path

def test_snapshot_contains_last_error():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert '"last_error": lead.last_error' in source
