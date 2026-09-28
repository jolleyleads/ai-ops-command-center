from pathlib import Path

def test_acceptance_result_marker_is_stable():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "PROVIDER_ACCEPTANCE_RESULT " in text
