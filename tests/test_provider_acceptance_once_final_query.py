from pathlib import Path

def test_acceptance_runner_queries_real_model():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "OutreachLead.query.filter_by(contact_email=recipient, company=marker)" in text
