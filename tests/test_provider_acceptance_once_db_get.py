from pathlib import Path

def test_runner_reloads_outreach_lead_model():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert "db.session.get(OutreachLead, lead.id)" in source
