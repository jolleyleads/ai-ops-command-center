from pathlib import Path

def test_runner_has_no_destructive_sql_words():
    text = Path("scripts/provider_acceptance_once.py").read_text().lower()
    assert "truncate" not in text
    assert "drop table" not in text
