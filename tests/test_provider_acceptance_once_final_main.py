from pathlib import Path

def test_acceptance_runner_has_executable_entrypoint():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'if __name__ == "__main__":' in text
    assert "main()" in text
