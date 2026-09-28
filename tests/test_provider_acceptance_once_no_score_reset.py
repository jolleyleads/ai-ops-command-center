from pathlib import Path

def test_existing_lead_score_is_not_mutated():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "lead.score =" not in text
