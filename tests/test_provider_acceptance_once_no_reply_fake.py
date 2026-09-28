from pathlib import Path

def test_runner_does_not_fabricate_reply_classification():
    source = Path("scripts/provider_acceptance_once.py").read_text().lower()
    assert "reply_classification =" not in source
    assert 'classification="interested"' not in source
