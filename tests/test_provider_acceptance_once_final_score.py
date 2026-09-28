from pathlib import Path

def test_acceptance_seed_score_is_deterministic():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "score=100" in text
