from pathlib import Path

def test_acceptance_config_gates_run_before_db_work():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    context = text.index("with app.app_context():")
    assert text.index("ACCEPTANCE_RECIPIENT_REQUIRED") < context
    assert text.index("GMAIL_FROM_EMAIL_REQUIRED") < context
    assert text.index("RECIPIENT_MUST_DIFFER_FROM_SENDER") < context
