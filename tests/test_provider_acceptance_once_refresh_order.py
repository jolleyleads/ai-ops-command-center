from pathlib import Path

def test_expire_all_occurs_after_scheduler():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.index("run_scheduled_outreach_cycle()") < text.index("db.session.expire_all()")
