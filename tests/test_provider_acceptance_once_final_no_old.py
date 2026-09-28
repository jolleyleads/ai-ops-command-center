from pathlib import Path

def test_acceptance_runner_has_no_legacy_model_import():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "app, db, Lead" not in text
    assert "company_name" not in text
