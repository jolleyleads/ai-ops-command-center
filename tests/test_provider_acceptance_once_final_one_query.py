from pathlib import Path

def test_acceptance_runner_has_single_lead_lookup():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.count("OutreachLead.query") == 1
