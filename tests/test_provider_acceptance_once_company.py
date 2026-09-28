from pathlib import Path

def test_snapshot_contains_company():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert '"company": lead.company' in source
