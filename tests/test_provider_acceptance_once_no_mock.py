from pathlib import Path

def test_runner_has_no_mock_imports():
    text = Path("scripts/provider_acceptance_once.py").read_text().lower()
    assert "unittest.mock" not in text
