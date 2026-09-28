from pathlib import Path

def test_acceptance_runner_has_no_raw_sql():
    text = Path("scripts/provider_acceptance_once.py").read_text().lower()
    assert "select *" not in text
    assert "insert into" not in text
