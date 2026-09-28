from pathlib import Path

def test_acceptance_runner_reuses_exact_test_lead():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "filter_by(contact_email=recipient, company=marker)" in text
