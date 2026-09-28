from pathlib import Path

def test_acceptance_runner_does_not_spawn_shell():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "subprocess" not in text
    assert "os.system" not in text
