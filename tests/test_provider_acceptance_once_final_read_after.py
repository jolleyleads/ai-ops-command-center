from pathlib import Path

def test_provider_state_is_read_after_cycle():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.index("cycle = run_scheduled_outreach_cycle()") < text.index("db.session.get(OutreachLead, lead.id)")
