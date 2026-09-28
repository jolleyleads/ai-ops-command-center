from pathlib import Path

def test_runner_records_utc_timestamp():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert "datetime.now(timezone.utc).isoformat()" in source
