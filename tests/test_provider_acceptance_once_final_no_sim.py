from pathlib import Path

def test_acceptance_runner_has_no_simulation_mode():
    text = Path("scripts/provider_acceptance_once.py").read_text().lower()
    assert "simulate" not in text
