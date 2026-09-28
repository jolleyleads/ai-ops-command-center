from pathlib import Path

def test_no_obsolete_company_name_filter():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "company_name ==" not in text
