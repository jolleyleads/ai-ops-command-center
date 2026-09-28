from pathlib import Path

def test_acceptance_runner_has_single_session_expire():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.count("db.session.expire_all()") == 1
