from pathlib import Path

def test_runner_uses_orm_not_raw_sql():
    text = Path("scripts/provider_acceptance_once.py").read_text().lower()
    assert "select *" not in text
    assert "insert into" not in text
