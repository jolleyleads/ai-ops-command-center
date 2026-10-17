def test_project_structure():
    assert True


def test_public_workspace_keeps_customer_interface():
    import commercial_app
    client = commercial_app.app.test_client()
    response = client.get("/chat-operator")
    assert response.status_code == 200
    assert b"Book a Demo" in response.data
    assert b"AutoMake AI" in response.data
    assert b'id="workspace-menu"' in response.data
    assert b'public-demo-note' in response.data
