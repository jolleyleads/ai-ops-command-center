from pathlib import Path

def test_recipient_gate_precedes_database_context():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.index("ACCEPTANCE_RECIPIENT_REQUIRED") < text.index("with app.app_context():")
