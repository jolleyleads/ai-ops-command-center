from pathlib import Path

def test_no_obsolete_email_filter():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "filter_by(email=" not in text
