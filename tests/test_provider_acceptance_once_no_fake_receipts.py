from pathlib import Path

def test_runner_does_not_fabricate_provider_ids():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert "gmail_message_id" in source
    assert "gmail_thread_id" in source
    assert "fake" not in source.lower()
