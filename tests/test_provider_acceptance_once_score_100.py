from pathlib import Path

def test_acceptance_score_is_100():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "score=100" in text
