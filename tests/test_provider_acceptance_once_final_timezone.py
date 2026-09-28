from pathlib import Path

def test_acceptance_timestamp_is_timezone_aware():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "timezone.utc" in text
