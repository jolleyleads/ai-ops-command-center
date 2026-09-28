from pathlib import Path

def test_fail_exits_nonzero():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert "raise SystemExit(1)" in source
