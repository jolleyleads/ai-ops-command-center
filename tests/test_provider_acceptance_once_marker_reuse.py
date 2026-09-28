from pathlib import Path

def test_marker_drives_reuse():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "marker" in text
    assert "first()" in text
