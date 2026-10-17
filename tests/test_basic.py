def test_project_structure():
    assert True


def test_public_workspace_link_returns_to_launch_page():
    import commercial_app
    client = commercial_app.app.test_client()
    response = client.get("/chat-operator")
    assert response.status_code == 303
    assert response.location == "/"
    page = client.get(response.location)
    assert b"Book a Demo" in page.data
    assert b"AutoMake AI" in page.data
