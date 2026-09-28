from pathlib import Path

def test_acceptance_runner_failure_is_machine_readable():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert '"reason": reason' in text
