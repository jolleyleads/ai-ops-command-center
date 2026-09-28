from pathlib import Path

def test_runner_only_reads_required_environment_keys():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.count("os.getenv(") == 2
