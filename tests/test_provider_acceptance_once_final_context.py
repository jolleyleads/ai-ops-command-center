from pathlib import Path

def test_acceptance_db_work_uses_app_context():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "with app.app_context():" in text
