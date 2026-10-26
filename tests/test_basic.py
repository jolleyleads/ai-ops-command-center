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


def test_main_domain_opens_marketing_homepage_and_preserves_app():
    import commercial_app
    client = commercial_app.app.test_client()
    response = client.get('/')
    assert response.status_code == 200
    assert b'Your next customer' in response.data
    assert b'Book a demo' in response.data
    assert b'info@automakeai.live' in response.data
    assert b'Illustrative reviews, not customer testimonials.' in response.data
    assert b'href="/chat-operator"' in response.data
    assert client.get('/chat-operator').status_code == 200
    assert client.get('/static/home.css').status_code == 200
    assert client.get('/static/home.js').status_code == 200
