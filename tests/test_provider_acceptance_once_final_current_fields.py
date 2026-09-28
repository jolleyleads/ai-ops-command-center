from pathlib import Path

def test_acceptance_runner_uses_current_field_names():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "company" in text
    assert "contact_email" in text
    assert "gmail_message_id" in text
    assert "gmail_thread_id" in text
