from pathlib import Path

def test_acceptance_runner_does_not_assign_provider_ids():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "gmail_message_id =" not in text
    assert "gmail_thread_id =" not in text
