from pathlib import Path

def test_new_acceptance_lead_is_persisted():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "db.session.add(lead)" in text
    assert "db.session.commit()" in text
