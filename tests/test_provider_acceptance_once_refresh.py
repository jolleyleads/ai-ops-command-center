from pathlib import Path

def test_runner_refreshes_after_scheduler():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert source.index("run_scheduled_outreach_cycle()") < source.index("db.session.expire_all()")
