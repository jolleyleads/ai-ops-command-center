from pathlib import Path

def test_runner_has_no_legacy_lead_constructor():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "Lead(" not in text.replace("OutreachLead(", "")
