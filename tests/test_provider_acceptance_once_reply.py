from pathlib import Path

def test_snapshot_contains_reply_state():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert '"replied_at": lead.replied_at' in source
