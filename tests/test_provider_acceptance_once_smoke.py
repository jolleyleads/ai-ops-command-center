import py_compile

def test_provider_acceptance_runner_compiles():
    py_compile.compile("scripts/provider_acceptance_once.py", doraise=True)
