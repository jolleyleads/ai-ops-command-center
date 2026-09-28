from pathlib import Path

def test_acceptance_result_is_json_serializable_output():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "json.dumps(result, default=str, sort_keys=True)" in text
