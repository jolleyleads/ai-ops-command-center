from pathlib import Path

def test_acceptance_runner_imports_real_outreach_model():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "from outreach_automation import OutreachLead" in text
