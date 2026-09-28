from pathlib import Path

def test_runner_does_not_execute_shell_commands():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "subprocess" not in text
    assert "os.system" not in text
