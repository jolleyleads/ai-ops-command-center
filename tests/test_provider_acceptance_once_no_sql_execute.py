from pathlib import Path

def test_runner_has_no_direct_sql_execute():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "db.session.execute" not in text
