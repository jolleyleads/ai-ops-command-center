from pathlib import Path

def test_runner_has_no_hardcoded_recipient_default():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'os.getenv("ACCEPTANCE_RECIPIENT") or ""' in source
