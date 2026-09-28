from pathlib import Path

def test_no_company_name_field():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "company_name" not in text
