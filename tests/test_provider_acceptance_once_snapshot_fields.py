from pathlib import Path

def test_core_snapshot_fields_are_present():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    for key in ("company", "contact_email", "status", "gmail_message_id", "gmail_thread_id", "sent_at", "replied_at", "last_error"):
        assert key in text
