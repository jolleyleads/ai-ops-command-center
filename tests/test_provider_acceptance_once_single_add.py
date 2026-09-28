from pathlib import Path

def test_runner_adds_one_model_instance():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.count("db.session.add(lead)") == 1
