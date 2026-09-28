from pathlib import Path

def test_acceptance_readback_follows_cycle():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.index("cycle = run_scheduled_outreach_cycle()") < text.index("db.session.expire_all()")
