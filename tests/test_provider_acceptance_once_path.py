from pathlib import Path

def test_runner_bootstraps_repo_root():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert "sys.path.insert(0" in source
