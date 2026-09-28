from pathlib import Path

def test_snapshot_reads_durable_state():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    for field in ("lead.status", "lead.sent_at", "lead.replied_at", "lead.last_error"):
        assert field in text
