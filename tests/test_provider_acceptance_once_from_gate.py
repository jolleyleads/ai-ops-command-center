from pathlib import Path

def test_gmail_sender_gate_precedes_database_context():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.index("GMAIL_FROM_EMAIL_REQUIRED") < text.index("with app.app_context():")
