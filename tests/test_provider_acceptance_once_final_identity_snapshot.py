from pathlib import Path

def test_acceptance_snapshot_includes_identity():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "contact_email" in text
    assert "company" in text
