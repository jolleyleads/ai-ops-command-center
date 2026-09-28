from pathlib import Path

def test_runner_has_no_monkeypatching():
    text = Path("scripts/provider_acceptance_once.py").read_text().lower()
    assert "monkeypatch" not in text
