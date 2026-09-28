def test_acceptance_runner_imports_flask_app():
    import scripts.provider_acceptance_once as runner
    assert runner.app is not None
    assert runner.db is not None
