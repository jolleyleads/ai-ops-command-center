from pathlib import Path

def test_model_import_precedes_scheduler_import():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.index("from outreach_automation import OutreachLead") < text.index("from outreach_scheduler import")
