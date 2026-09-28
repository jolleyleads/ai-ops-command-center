from pathlib import Path

def test_runner_reports_durable_lead_id():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert '"lead_id": lead.id' in source
