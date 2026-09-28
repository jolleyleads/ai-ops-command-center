from pathlib import Path

def test_acceptance_result_json_is_sorted():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "sort_keys=True" in text
