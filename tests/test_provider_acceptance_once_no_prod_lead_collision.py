from pathlib import Path

def test_marker_is_used_in_lookup_and_constructor():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.count("company=marker") >= 2
