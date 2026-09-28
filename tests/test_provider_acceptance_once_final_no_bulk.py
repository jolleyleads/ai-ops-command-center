from pathlib import Path

def test_acceptance_runner_does_not_iterate_all_leads():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert ".all()" not in text
