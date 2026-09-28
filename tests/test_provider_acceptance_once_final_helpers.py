def test_acceptance_runner_helpers_are_callable():
    import scripts.provider_acceptance_once as runner
    assert callable(runner.main)
    assert callable(runner.snapshot)
    assert callable(runner.fail)
