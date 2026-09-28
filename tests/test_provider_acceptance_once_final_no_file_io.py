from pathlib import Path

def test_acceptance_runner_does_not_write_local_files():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert ".write_text(" not in text
