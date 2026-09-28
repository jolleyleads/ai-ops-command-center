from pathlib import Path

def test_runner_has_no_fake_proof_constants():
    text = Path("scripts/provider_acceptance_once.py").read_text().lower()
    assert "fake_" not in text
    assert "dummy_" not in text
