from pathlib import Path

def test_acceptance_runner_constructs_real_model():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "lead = OutreachLead(" in text
