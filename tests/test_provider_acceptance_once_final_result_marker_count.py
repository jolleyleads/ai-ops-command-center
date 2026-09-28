from pathlib import Path

def test_acceptance_result_marker_exists():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.count("PROVIDER_ACCEPTANCE_RESULT") >= 1
