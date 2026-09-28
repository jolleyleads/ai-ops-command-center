from pathlib import Path

def test_new_lead_is_committed_before_scheduler():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.index("db.session.commit()") < text.index("run_scheduled_outreach_cycle()")
