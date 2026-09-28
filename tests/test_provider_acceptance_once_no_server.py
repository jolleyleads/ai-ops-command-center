from pathlib import Path

def test_runner_does_not_start_web_server():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "app.run(" not in text
