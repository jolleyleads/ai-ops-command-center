from pathlib import Path

def test_uses_real_company_field():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "company=marker" in text
