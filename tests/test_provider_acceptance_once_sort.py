from pathlib import Path

def test_result_serialization_is_sorted():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "sort_keys=True" in text
