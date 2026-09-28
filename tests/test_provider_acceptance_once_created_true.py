from pathlib import Path

def test_runner_marks_created_after_commit():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert source.index("db.session.commit()") < source.index("created = True")
