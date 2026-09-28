from pathlib import Path

def test_machine_readable_output_cannot_regress():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "PROVIDER_ACCEPTANCE_RESULT" in text
    assert "json.dumps" in text
