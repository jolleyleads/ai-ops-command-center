from pathlib import Path

def test_acceptance_runner_adds_only_test_lead():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.count("db.session.add(lead)") == 1
