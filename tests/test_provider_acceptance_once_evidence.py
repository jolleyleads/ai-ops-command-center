from pathlib import Path

def test_runner_seeds_valid_evidence_json():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'evidence_json="[]"' in source
