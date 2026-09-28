from pathlib import Path

def test_runner_requires_email_shape():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert '"@" not in recipient' in text
