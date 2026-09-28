def test_acceptance_runner_imports_scheduler_callable():
    import scripts.provider_acceptance_once as runner
    assert callable(runner.run_scheduled_outreach_cycle)
