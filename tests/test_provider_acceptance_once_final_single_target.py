from pathlib import Path

def test_acceptance_runner_targets_exactly_one_matching_lead():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert ".first()" in text
    assert ".all()" not in text
