def test_scheduler_binds_persisted_oauth_resolver():
    import gmail_connect
    import gmail_outreach_state
    import outreach_automation
    import outreach_scheduler  # noqa: F401

    assert gmail_outreach_state.gmail_access_token is gmail_connect.gmail_access_token
    assert outreach_automation.gmail_access_token is gmail_connect.gmail_access_token
