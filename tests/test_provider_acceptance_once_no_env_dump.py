from pathlib import Path

def test_runner_does_not_dump_environment():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "os.environ" not in text
