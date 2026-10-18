def test_project_structure():
    assert True


def test_chat_operator_route_serves_connected_ui():
    import commercial_app
    client = commercial_app.app.test_client()
    response = client.get("/chat-operator")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "AutoMake AI" in body
    assert "Ask.Automate.Execute" in body
    assert "/api/research/jobs" in body
    assert "/api/outreach/leads" in body
    assert "verification and safe-send checks" in body


def test_main_domain_opens_existing_customer_chat():
    import commercial_app
    client = commercial_app.app.test_client()
    response = client.get('/')
    assert response.status_code == 302
    assert response.location == '/chat-operator'
    page = client.get('/', follow_redirects=True)
    assert page.status_code == 200
    assert b'id="workspace-menu"' in page.data
    assert b'Message AutoMake AI' in page.data
    assert b'public-demo-note' not in page.data
    assert b'Book a Demo' not in page.data
    assert b'account-login' not in page.data
    assert b'account-logout' not in page.data
    assert b'/auth/session' not in page.data
