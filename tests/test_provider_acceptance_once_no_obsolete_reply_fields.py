from pathlib import Path

def test_snapshot_does_not_use_nonexistent_reply_fields():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "reply_message_id" not in text
    assert "reply_classification" not in text
