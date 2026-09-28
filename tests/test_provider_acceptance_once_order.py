from pathlib import Path

def test_scheduler_runs_before_durable_reload():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert source.index("cycle = run_scheduled_outreach_cycle()") < source.index("lead = db.session.get(OutreachLead, lead.id)")
