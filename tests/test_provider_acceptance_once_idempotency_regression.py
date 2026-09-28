from pathlib import Path

def test_acceptance_lead_reuse_cannot_regress():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "filter_by(contact_email=recipient, company=marker)" in text
    assert "if lead is None:" in text
