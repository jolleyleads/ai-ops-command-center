from pathlib import Path

def test_acceptance_runner_sets_repo_path_before_app_import():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.index("sys.path.insert") < text.index("from app import")
