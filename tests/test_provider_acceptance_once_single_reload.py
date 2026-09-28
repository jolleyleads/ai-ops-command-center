from pathlib import Path

def test_runner_has_one_durable_reload():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.count("db.session.get(OutreachLead, lead.id)") == 1
