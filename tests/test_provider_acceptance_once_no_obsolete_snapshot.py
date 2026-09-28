from pathlib import Path

def test_snapshot_uses_current_model_names():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "company_name" not in text
    assert "outreach_status" not in text
    assert "next_action" not in text
