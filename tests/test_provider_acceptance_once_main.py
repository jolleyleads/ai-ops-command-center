from pathlib import Path

def test_runner_has_main_entrypoint():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'if __name__ == "__main__":' in source
