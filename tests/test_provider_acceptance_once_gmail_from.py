from pathlib import Path

def test_sender_comes_from_gmail_from_email():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'os.getenv("GMAIL_FROM_EMAIL")' in text
