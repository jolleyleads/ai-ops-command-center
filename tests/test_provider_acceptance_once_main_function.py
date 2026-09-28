from pathlib import Path

def test_runner_has_main_function():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "def main():" in text
