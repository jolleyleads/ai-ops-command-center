from pathlib import Path

def test_runner_has_one_outreach_lead_query():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.count("OutreachLead.query") == 1
