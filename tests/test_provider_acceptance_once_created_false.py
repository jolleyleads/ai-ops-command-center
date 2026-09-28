from pathlib import Path

def test_runner_defaults_created_false():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert "created = False" in source
