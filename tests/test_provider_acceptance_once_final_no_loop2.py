from pathlib import Path

def test_acceptance_runner_has_no_polling_loop():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "while " not in text
    assert "sleep(" not in text
