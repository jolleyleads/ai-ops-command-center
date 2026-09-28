def test_provider_acceptance_runner_imports_real_model():
    import scripts.provider_acceptance_once as runner
    from outreach_automation import OutreachLead
    assert runner.OutreachLead is OutreachLead
