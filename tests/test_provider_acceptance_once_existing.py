from pathlib import Path

def test_existing_acceptance_lead_is_reused():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "if lead is None:" in text
    assert "created = False" in text
