from pathlib import Path

def test_no_hardcoded_test_recipient():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "jolleysalesfloor" not in text
