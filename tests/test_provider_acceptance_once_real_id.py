from pathlib import Path

def test_snapshot_reads_real_primary_key():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert '"id": lead.id' in text
