from pathlib import Path

def test_production_scheduler_path_cannot_regress():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "run_scheduled_outreach_cycle()" in text
    assert "send_gmail(" not in text
