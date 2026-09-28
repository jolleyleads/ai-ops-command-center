from pathlib import Path

def test_acceptance_before_snapshot_precedes_cycle():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.index("before = snapshot(lead)") < text.index("cycle = run_scheduled_outreach_cycle()")
