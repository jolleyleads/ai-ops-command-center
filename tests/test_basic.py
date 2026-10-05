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
    assert "/api/smart-search" in body
    assert "/api/outreach/leads" in body
    assert "verification and safe-send checks" in body
