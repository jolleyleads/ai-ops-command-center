from pathlib import Path

def test_acceptance_runner_does_not_fabricate_receipts():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "lead.gmail_message_id =" not in text
    assert "lead.gmail_thread_id =" not in text
    assert "lead.replied_at =" not in text
