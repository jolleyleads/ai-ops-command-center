from pathlib import Path

def test_runner_imports_json():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "import json" in text
