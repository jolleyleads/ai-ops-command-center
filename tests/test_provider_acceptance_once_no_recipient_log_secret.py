from pathlib import Path

def test_runner_does_not_dump_environment_with_recipient():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "dict(os.environ" not in text
