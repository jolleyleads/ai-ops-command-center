from pathlib import Path

def test_runner_reads_acceptance_recipient_env():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'os.getenv("ACCEPTANCE_RECIPIENT")' in source
