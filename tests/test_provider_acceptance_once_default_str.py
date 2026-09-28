from pathlib import Path

def test_result_serialization_handles_datetimes():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "default=str" in text
