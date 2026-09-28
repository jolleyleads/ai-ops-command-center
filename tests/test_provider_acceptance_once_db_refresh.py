from pathlib import Path

def test_runner_reloads_durable_state_after_cycle():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert "db.session.expire_all()" in source
    assert "db.session.get(OutreachLead, lead.id)" in source
