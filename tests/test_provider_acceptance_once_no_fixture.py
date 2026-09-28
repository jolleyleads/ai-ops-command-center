from pathlib import Path

def test_runner_has_no_fixture_dependency():
    text = Path("scripts/provider_acceptance_once.py").read_text().lower()
    assert "pytest" not in text
