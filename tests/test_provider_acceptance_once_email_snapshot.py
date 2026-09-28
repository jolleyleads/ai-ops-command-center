from pathlib import Path

def test_snapshot_contains_contact_email():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert '"contact_email": lead.contact_email' in source
