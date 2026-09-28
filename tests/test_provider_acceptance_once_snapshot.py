from pathlib import Path

def test_snapshot_contains_gmail_provider_ids():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert '"gmail_message_id": lead.gmail_message_id' in source
    assert '"gmail_thread_id": lead.gmail_thread_id' in source
