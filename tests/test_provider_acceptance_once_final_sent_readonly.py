from pathlib import Path

def test_acceptance_runner_only_reads_send_state():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "lead.sent_at" in text
    assert "lead.sent_at =" not in text
