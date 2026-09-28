from pathlib import Path

def test_runner_seeds_explicit_acceptance_message():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert "AI Ops provider acceptance test" in source
    assert "Please reply that you are interested" in source
