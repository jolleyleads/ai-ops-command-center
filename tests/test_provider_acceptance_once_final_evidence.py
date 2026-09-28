from pathlib import Path

def test_acceptance_seed_has_valid_empty_evidence():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'evidence_json="[]"' in text
