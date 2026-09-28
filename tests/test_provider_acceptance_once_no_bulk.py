from pathlib import Path

def test_runner_has_no_lead_iteration():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "for lead in" not in text
