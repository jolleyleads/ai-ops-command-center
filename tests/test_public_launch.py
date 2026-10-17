import pytest
import commercial_app
import customer_demo as demo
import outreach_automation as oa


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('OPERATOR_CONTROL_TOKEN', 'launch-test-secret')
    monkeypatch.setattr(demo, 'enqueue_execution', lambda *a, **k:pytest.fail('Public demo launched real work'))
    return commercial_app.app.test_client()


def test_home_and_booking_are_public_without_database_queries(client, monkeypatch):
    monkeypatch.setattr(oa.db.session, 'execute', lambda *a, **k:pytest.fail('Public page queried private data'))
    page=client.get('/')
    assert page.status_code==200
    assert b'Book a Demo' in page.data and b'href="/login"' in page.data
    assert b'Sign up' not in page.data and b'Create account' not in page.data
    booking=client.get('/book-demo')
    assert booking.status_code==200
    assert b'mailto:jolleyleads@gmail.com' in booking.data
    assert b'confirmed after Matthew replies' in booking.data


def test_public_demo_is_sample_only_and_has_no_live_api_calls(client, monkeypatch):
    monkeypatch.setattr(oa.db.session, 'execute', lambda *a, **k:pytest.fail('Public demo queried private records'))
    page=client.get('/demo')
    assert page.status_code==200
    assert b'Illustrative sample data only' in page.data
    assert b'Example Coastal HVAC' in page.data
    assert b'fetch(' not in page.data and b'LAUNCH CAMPAIGN' not in page.data
    data=client.get('/api/demo/leads')
    assert data.json['is_demo'] is True
    assert all(str(row['id']).startswith('sample-') for row in data.json['leads'])


def test_anonymous_visitors_cannot_enter_workspace_or_use_real_demo_endpoints(client):
    assert client.get('/chat-operator').status_code==303
    assert client.get('/chat-operator').location=='/'
    assert client.get('/api/chat/dashboard').status_code==401
    assert client.post('/api/demo/campaigns/launch', json={'target_customer':'anything'}).status_code==401
    assert client.get('/api/demo/campaigns/jobs/private-job').status_code==401


def test_approved_operator_keeps_existing_workspace(client):
    page=client.get('/chat-operator',headers={'X-Operator-Token':'launch-test-secret'})
    assert page.status_code==200 and b'id="workspace-menu"' in page.data
    assert b'/api/chat/campaigns/launch' in page.data


def test_existing_browser_session_keeps_demo_campaign_csrf_requirement(client):
    with client.session_transaction() as session:
        with oa.app.test_request_context():session['operator_auth']=oa._session_proof()
    assert client.post('/api/demo/campaigns/launch',json={'target_customer':'anything'}).status_code==403
