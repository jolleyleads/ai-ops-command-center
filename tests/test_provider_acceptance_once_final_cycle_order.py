from pathlib import Path

def test_acceptance_cycle_runs_after_seed_lookup():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.index("OutreachLead.query") < text.index("cycle = run_scheduled_outreach_cycle()")
