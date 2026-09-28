from pathlib import Path

def test_runner_does_not_include_sender_in_result_payload():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert '"sender": sender' not in source
