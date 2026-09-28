from pathlib import Path

def test_acceptance_runner_reports_timestamp():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert '"timestamp": datetime.now(timezone.utc).isoformat()' in text
