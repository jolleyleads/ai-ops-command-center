from pathlib import Path

def test_runner_queries_outreach_lead():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "OutreachLead.query" in text
