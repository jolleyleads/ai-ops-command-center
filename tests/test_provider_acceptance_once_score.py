from pathlib import Path

def test_runner_uses_high_acceptance_score():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert "score=100" in source
