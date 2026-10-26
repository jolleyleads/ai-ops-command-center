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


def test_main_domain_opens_public_homepage():
    import commercial_app
    client = commercial_app.app.test_client()
    page = client.get('/')
    assert page.status_code == 200
    assert b'Less busywork.' in page.data
    assert b'Book a Demo' in page.data
    assert b'href="/login"' in page.data
    assert b'id="book-demo"' in page.data
    assert b'mailto:jolleyleads@gmail.com' in page.data
    assert b'not a real customer review' not in page.data
    assert client.get('/static/home.css').status_code == 200
    assert client.get('/static/home.js').status_code == 200
    assert client.get('/chat-operator/automake-logo.svg').status_code == 200
    assert client.get('/login').status_code == 200
    chat = client.get('/chat-operator')
    assert chat.status_code == 200
    assert b'id="workspace-menu"' in chat.data
    assert b'Message AutoMake AI' in chat.data
