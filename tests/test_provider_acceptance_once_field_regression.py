from pathlib import Path

def test_original_field_mismatch_cannot_regress():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "company_name" not in text
    assert "contact_email" in text
    assert "company=marker" in text
