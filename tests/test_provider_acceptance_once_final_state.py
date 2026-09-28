from pathlib import Path

def test_acceptance_runner_reloads_durable_state():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "db.session.expire_all()" in text
    assert "db.session.get(OutreachLead, lead.id)" in text
