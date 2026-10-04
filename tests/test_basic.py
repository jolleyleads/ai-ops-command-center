def test_project_structure():
    assert True


def test_chat_operator_route_serves_connected_ui():
    import commercial_app
    client = commercial_app.app.test_client()
    response = client.get("/chat-operator")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "AI Ops Operator" in body
    assert "/api/smart-search" in body
    assert "/api/outreach/leads/" in body
    assert "Safe-send gates on" in body
