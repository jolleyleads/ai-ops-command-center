from pathlib import Path

def test_runner_imports_sys():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "import sys" in text
