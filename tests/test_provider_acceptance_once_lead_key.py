from pathlib import Path

def test_runner_reports_lead_id_key():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert '"lead_id"' in text
