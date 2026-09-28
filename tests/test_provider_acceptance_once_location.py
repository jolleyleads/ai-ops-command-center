from pathlib import Path

def test_runner_marks_acceptance_location():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'location="Production Acceptance"' in source
