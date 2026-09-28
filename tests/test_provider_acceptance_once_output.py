from pathlib import Path

def test_runner_emits_machine_readable_result_marker():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert "PROVIDER_ACCEPTANCE_RESULT" in source
