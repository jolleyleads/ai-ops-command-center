from pathlib import Path

def test_runner_prints_result_payload():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "json.dumps(result" in text
