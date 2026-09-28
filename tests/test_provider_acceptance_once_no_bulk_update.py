from pathlib import Path

def test_runner_has_no_bulk_update_or_delete():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert ".update(" not in text
    assert ".delete(" not in text
