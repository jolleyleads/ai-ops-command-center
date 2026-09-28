from pathlib import Path

def test_runner_uses_single_result_marker_name():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.count("PROVIDER_ACCEPTANCE_RESULT") == 2
