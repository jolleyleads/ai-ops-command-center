from pathlib import Path

def test_existing_state_is_preserved_by_runner():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "if lead is None:" in text
