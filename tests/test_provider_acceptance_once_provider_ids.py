from pathlib import Path

def test_snapshot_reads_provider_ids():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "lead.gmail_message_id" in text
    assert "lead.gmail_thread_id" in text
