from pathlib import Path

def test_acceptance_runner_only_reads_error_state():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "lead.last_error" in text
    assert "lead.last_error =" not in text
