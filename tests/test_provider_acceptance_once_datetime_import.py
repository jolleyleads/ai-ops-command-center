from pathlib import Path

def test_runner_imports_timezone():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "from datetime import datetime, timezone" in text
