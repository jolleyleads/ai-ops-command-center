from pathlib import Path

def test_runner_has_acceptance_subject_and_body():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "subject=" in text
    assert "body=" in text
