from pathlib import Path

def test_app_module_is_not_lead_model_source():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "from app import Lead" not in text
