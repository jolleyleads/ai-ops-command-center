from pathlib import Path

def test_acceptance_result_has_utc_timestamp():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "datetime.now(timezone.utc).isoformat()" in text
