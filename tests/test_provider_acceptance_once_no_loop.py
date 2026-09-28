from pathlib import Path

def test_runner_has_no_loop_constructs():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "while " not in text
