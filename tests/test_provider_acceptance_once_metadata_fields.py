from pathlib import Path

def test_acceptance_constructor_has_metadata_fields():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "location=" in text
    assert "source_url=" in text
    assert "evidence_json=" in text
