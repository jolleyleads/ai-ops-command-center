from pathlib import Path

def test_runner_does_not_print_oauth_secrets():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert "GOOGLE_CLIENT_SECRET" not in source
    assert "GOOGLE_REFRESH_TOKEN" not in source
