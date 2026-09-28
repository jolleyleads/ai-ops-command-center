from pathlib import Path

def test_snapshot_reads_lead_identity():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    for field in ("lead.id", "lead.company", "lead.contact_email"):
        assert field in text
