from pathlib import Path

def test_acceptance_result_handles_datetime_values():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "default=str" in text
