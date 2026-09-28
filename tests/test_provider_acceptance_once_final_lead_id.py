from pathlib import Path

def test_acceptance_runner_reports_lead_id():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert '"lead_id": lead.id' in text
