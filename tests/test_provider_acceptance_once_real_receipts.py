from pathlib import Path

def test_provider_ids_are_observed_after_cycle():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.index("run_scheduled_outreach_cycle()") < text.rindex("snapshot(lead)")
