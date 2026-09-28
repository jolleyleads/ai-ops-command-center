from pathlib import Path

def test_acceptance_runner_has_no_direct_network_calls():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "requests." not in text
    assert "httpx." not in text
