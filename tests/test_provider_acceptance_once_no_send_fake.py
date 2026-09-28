from pathlib import Path

def test_runner_only_reads_gmail_ids_from_lead():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert '"gmail_message_id": lead.gmail_message_id' in source
    assert '"gmail_thread_id": lead.gmail_thread_id' in source
