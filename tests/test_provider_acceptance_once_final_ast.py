import ast
from pathlib import Path

def test_acceptance_runner_ast_parses_cleanly():
    ast.parse(Path("scripts/provider_acceptance_once.py").read_text())
