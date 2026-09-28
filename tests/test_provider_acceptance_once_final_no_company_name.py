from pathlib import Path

def test_acceptance_runner_does_not_use_company_name():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "company_name" not in text
