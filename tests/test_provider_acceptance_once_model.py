from pathlib import Path

def test_runner_imports_exact_outreach_model():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert "from outreach_automation import OutreachLead" in source
