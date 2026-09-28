from pathlib import Path

def test_acceptance_runner_reloads_real_model():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "db.session.get(OutreachLead, lead.id)" in text
