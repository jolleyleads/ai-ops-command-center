from pathlib import Path

def test_runner_reuses_acceptance_lead():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert "filter_by(contact_email=recipient, company=marker)" in source
