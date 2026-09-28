from pathlib import Path

def test_acceptance_runner_does_not_retry_hidden_failures():
    text = Path("scripts/provider_acceptance_once.py").read_text().lower()
    assert "retry" not in text
