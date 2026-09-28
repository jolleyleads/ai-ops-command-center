from pathlib import Path

def test_acceptance_lead_is_source_verified():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "SOURCE_VERIFIED" in text
