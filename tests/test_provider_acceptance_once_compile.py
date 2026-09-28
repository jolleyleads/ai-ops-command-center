import ast
from pathlib import Path

def test_acceptance_runner_parses():
    ast.parse(Path("scripts/provider_acceptance_once.py").read_text())
