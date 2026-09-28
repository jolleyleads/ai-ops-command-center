from pathlib import Path

def test_runner_uses_real_outreach_lead_field_names():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert "contact_email=recipient" in source
    assert "company=marker" in source
    assert "company_name=" not in source
