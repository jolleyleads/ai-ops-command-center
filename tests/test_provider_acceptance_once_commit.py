from pathlib import Path

def test_runner_commits_created_lead():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert "db.session.add(lead)" in source
    assert "db.session.commit()" in source
