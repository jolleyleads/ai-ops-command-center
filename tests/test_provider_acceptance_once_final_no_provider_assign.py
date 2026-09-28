from pathlib import Path

def test_runner_does_not_assign_provider_state():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    for assignment in ("lead.gmail_message_id =", "lead.gmail_thread_id =", "lead.sent_at =", "lead.replied_at ="):
        assert assignment not in text
