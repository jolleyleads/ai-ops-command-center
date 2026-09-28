from pathlib import Path

def test_existing_acceptance_lead_is_not_reset():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "lead.status =" not in text
    assert "lead.subject =" not in text
    assert "lead.body =" not in text
