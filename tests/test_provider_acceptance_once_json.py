from pathlib import Path

def test_runner_serializes_provider_state():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert "json.dumps(result, default=str, sort_keys=True)" in source
