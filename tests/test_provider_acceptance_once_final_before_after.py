from pathlib import Path

def test_acceptance_runner_has_before_and_after_proof():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "before = snapshot(lead)" in text
    assert '"after"' in text
