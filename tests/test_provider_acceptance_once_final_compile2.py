import py_compile

def test_acceptance_runner_compiles_cleanly():
    py_compile.compile("scripts/provider_acceptance_once.py", doraise=True)
