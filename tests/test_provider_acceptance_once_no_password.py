from pathlib import Path

def test_runner_contains_no_password_material():
    text = Path("scripts/provider_acceptance_once.py").read_text().lower()
    assert "password" not in text
    assert "secret" not in text
