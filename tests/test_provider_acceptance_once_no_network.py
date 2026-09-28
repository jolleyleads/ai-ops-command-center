from pathlib import Path

def test_runner_has_no_direct_network_library():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "urllib" not in text
    assert "httpx" not in text
