from pathlib import Path

def test_acceptance_runner_bootstraps_repo_path():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "sys.path.insert(0" in text
