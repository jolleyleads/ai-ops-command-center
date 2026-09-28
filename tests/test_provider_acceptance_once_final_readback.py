from pathlib import Path

def test_acceptance_runner_reads_state_back_after_cycle():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.index("run_scheduled_outreach_cycle()") < text.index("db.session.expire_all()")
    assert text.index("db.session.expire_all()") < text.index("db.session.get(OutreachLead, lead.id)")
