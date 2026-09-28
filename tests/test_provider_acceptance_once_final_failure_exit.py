from pathlib import Path

def test_acceptance_config_failure_exits_nonzero():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "raise SystemExit(1)" in text
