from pathlib import Path

def test_runner_does_not_mutate_lead_after_cycle():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    cycle = text.index("cycle = run_scheduled_outreach_cycle()")
    assert "lead.status =" not in text[cycle:]
