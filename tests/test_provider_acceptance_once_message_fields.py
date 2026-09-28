from pathlib import Path

def test_acceptance_constructor_has_message_fields():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "subject=" in text
    assert "body=" in text
