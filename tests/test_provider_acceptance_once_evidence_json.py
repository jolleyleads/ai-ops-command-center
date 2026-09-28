import json
from pathlib import Path

def test_acceptance_evidence_literal_is_valid_json():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'evidence_json="[]"' in text
    assert json.loads("[]") == []
