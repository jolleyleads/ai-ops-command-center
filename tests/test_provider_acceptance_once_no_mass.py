from pathlib import Path

def test_runner_does_not_query_all_leads():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert ".all()" not in text
