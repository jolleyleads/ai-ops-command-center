def test_acceptance_runner_imports_same_outreach_model():
    import scripts.provider_acceptance_once as runner
    from outreach_automation import OutreachLead
    assert runner.OutreachLead is OutreachLead
