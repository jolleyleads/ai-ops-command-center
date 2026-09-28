from pathlib import Path

def test_provider_receipts_remain_read_only():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "lead.gmail_message_id =" not in text
    assert "lead.gmail_thread_id =" not in text
