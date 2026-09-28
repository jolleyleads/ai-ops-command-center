from pathlib import Path

def test_acceptance_seed_is_committed_before_cycle():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.index("db.session.commit()") < text.index("cycle = run_scheduled_outreach_cycle()")
