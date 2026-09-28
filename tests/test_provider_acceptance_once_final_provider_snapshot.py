from pathlib import Path

def test_acceptance_snapshot_includes_provider_ids():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "gmail_message_id" in text
    assert "gmail_thread_id" in text
