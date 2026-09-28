from pathlib import Path

def test_runner_snapshots_before_and_after():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.count("snapshot(lead)") >= 2
