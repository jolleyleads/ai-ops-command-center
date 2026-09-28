from pathlib import Path

def test_acceptance_runner_only_reads_reply_state():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "lead.replied_at" in text
    assert "lead.replied_at =" not in text
