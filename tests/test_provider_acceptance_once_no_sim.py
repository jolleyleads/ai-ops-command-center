from pathlib import Path

def test_runner_has_no_simulation_flag():
    source = Path("scripts/provider_acceptance_once.py").read_text().lower()
    assert "simulate" not in source
    assert "mock" not in source
