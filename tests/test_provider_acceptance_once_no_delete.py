from pathlib import Path

def test_runner_does_not_delete_rows():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "db.session.delete" not in text
