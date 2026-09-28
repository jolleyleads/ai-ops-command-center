from pathlib import Path

def test_acceptance_runner_has_no_mocking():
    text = Path("scripts/provider_acceptance_once.py").read_text().lower()
    assert "mock" not in text
