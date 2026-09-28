from pathlib import Path

def test_existing_lead_status_is_not_reset():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.count('status="qualified"') == 1
