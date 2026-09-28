from pathlib import Path

def test_acceptance_seed_has_explicit_subject():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "AI Ops provider acceptance test" in text
