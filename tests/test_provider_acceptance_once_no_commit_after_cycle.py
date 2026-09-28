from pathlib import Path

def test_runner_does_not_commit_provider_state_after_cycle():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    cycle = text.index("cycle = run_scheduled_outreach_cycle()")
    assert "db.session.commit()" not in text[cycle:]
