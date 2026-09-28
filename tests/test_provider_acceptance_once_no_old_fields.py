from pathlib import Path

def test_runner_does_not_use_obsolete_fields():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "company_name" not in text
    assert "qualification_status" not in text
