from pathlib import Path

def test_runner_treats_provider_receipt_fields_as_read_only():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    for field in ("gmail_message_id", "gmail_thread_id", "sent_at", "replied_at"):
        assert f"lead.{field} =" not in text
