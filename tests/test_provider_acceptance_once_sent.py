from pathlib import Path

def test_snapshot_contains_send_timestamp():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert '"sent_at": lead.sent_at' in source
