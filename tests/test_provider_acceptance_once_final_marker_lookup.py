from pathlib import Path

def test_acceptance_marker_is_part_of_lookup():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "company=marker" in text
