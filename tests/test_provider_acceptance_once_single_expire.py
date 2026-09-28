from pathlib import Path

def test_runner_expires_session_once():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.count("db.session.expire_all()") == 1
