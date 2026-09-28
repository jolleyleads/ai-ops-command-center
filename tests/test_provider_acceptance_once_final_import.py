def test_acceptance_runner_module_imports():
    import scripts.provider_acceptance_once as runner
    assert runner.OutreachLead.__tablename__ == "outreach_lead"
