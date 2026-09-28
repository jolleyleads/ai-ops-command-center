from pathlib import Path

def test_acceptance_snapshot_includes_send_reply_state():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "sent_at" in text
    assert "replied_at" in text
