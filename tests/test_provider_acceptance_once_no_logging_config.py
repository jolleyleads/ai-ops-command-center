from pathlib import Path

def test_runner_does_not_change_logging_configuration():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "logging.basicConfig" not in text
