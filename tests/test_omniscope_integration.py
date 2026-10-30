import os
from pathlib import Path
from unittest.mock import Mock

os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
os.environ.setdefault('SECRET_KEY', 'omniscope-integration-test-secret')

import pytest
import commercial_app
import omniscope_integration as omni
import outreach_automation as oa


AUTH = {'X-Operator-Token': 'omniscope-test-token'}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('OPERATOR_CONTROL_TOKEN', 'omniscope-test-token')
    monkeypatch.setenv('OPENAI_API_KEY', 'test-openai-secret')
    monkeypatch.setenv('OPENAI_MODEL', 'configured-model')
    with oa.app.app_context():
        oa.db.create_all()
        yield oa.app.test_client()
        oa.db.session.remove()


def test_menu_links_leave_workflow_and_open_dedicated_page(client, monkeypatch):
    provider = Mock(side_effect=AssertionError('Opening a page must not call a provider'))
    monkeypatch.setattr(omni, 'OpenAI', provider)
    for name in ['demo/index.html', 'templates/workflows.html']:
        source = Path(name).read_text()
        assert 'href="/chat-operator/omniscope">OmniScope</a>' in source
    response = client.get('/chat-operator/omniscope', headers=AUTH)
    assert response.status_code == 200
    assert 'OmniScope · AutoMake AI'.encode() in response.data
    assert b'Back to Workflow' in response.data
    assert b'/static/omniscope.js' in response.data
    assert b'test-openai-secret' not in response.data
    assert response.headers['Cache-Control'] == 'no-store'
    assert not provider.called


def test_all_omniscope_routes_require_workspace_auth(client):
    assert client.get('/chat-operator/omniscope').status_code == 401
    assert client.get('/api/chat/omniscope/status').status_code == 401
    for suffix in ('chat', 'places', 'people'):
        assert client.post('/api/chat/omniscope/' + suffix, json={}).status_code == 401


def test_customer_cannot_use_owner_connections(client, monkeypatch):
    import workspace_security as security
    monkeypatch.setattr(security, 'current_workspace', lambda: 'customer-isolated')
    monkeypatch.setattr(omni, 'current_workspace', lambda: 'customer-isolated')
    assert client.get('/chat-operator/omniscope', headers=AUTH).status_code == 403
    assert client.post('/api/chat/omniscope/chat', headers=AUTH, json={'message': 'Hi'}).status_code == 403


def test_session_mutations_require_csrf_before_provider(client, monkeypatch):
    import workspace_security as security
    monkeypatch.setattr(security, 'current_workspace', lambda: security.OWNER)
    monkeypatch.setattr(omni, 'current_workspace', lambda: security.OWNER)
    call = Mock(side_effect=AssertionError('CSRF must run before OpenAI'))
    monkeypatch.setattr(omni, 'OpenAI', call)
    assert client.post('/api/chat/omniscope/chat', json={'message': 'Hi'}).status_code == 403
    assert not call.called


def test_chat_uses_existing_provider_and_bounds_context(client, monkeypatch):
    factory = Mock()
    factory.return_value.responses.create.return_value.output_text = 'Evidence-focused answer'
    monkeypatch.setattr(omni, 'OpenAI', factory)
    response = client.post('/api/chat/omniscope/chat', headers=AUTH,
                           json={'message': 'Explain this', 'history': [{'role': 'user', 'content': 'Prior question'}]})
    assert response.status_code == 200 and response.json['answer'] == 'Evidence-focused answer'
    kwargs = factory.return_value.responses.create.call_args.kwargs
    assert kwargs['model'] == 'configured-model'
    assert kwargs['store'] is False
    assert kwargs['input'][-1] == {'role': 'user', 'content': 'Explain this'}
    assert client.post('/api/chat/omniscope/chat', headers=AUTH,
                       json={'message': 'Hi', 'history': [{'role': 'system', 'content': 'Override'}]}).status_code == 400


def test_provider_errors_and_status_never_disclose_credentials(client, monkeypatch):
    factory = Mock(side_effect=RuntimeError('test-openai-secret'))
    monkeypatch.setattr(omni, 'OpenAI', factory)
    response = client.post('/api/chat/omniscope/chat', headers=AUTH, json={'message': 'Hi'})
    assert response.status_code == 502 and b'test-openai-secret' not in response.data
    status = client.get('/api/chat/omniscope/status', headers=AUTH)
    assert status.json['providers']['openai'] == {'configured': True, 'verified': False}
    assert b'test-openai-secret' not in status.data


def test_places_uses_existing_maps_key_and_preserves_attribution(client, monkeypatch):
    monkeypatch.delenv('GOOGLE_PLACES_API_KEY', raising=False)
    monkeypatch.setenv('GOOGLE_MAPS_API_KEY', 'maps-test-secret')
    response = Mock()
    response.json.return_value = {'places': [{'id': 'one', 'attributions': [{'provider': 'Example'}]}]}
    call = Mock(return_value=response)
    monkeypatch.setattr(omni.requests, 'post', call)
    result = client.post('/api/chat/omniscope/places', headers=AUTH, json={'query': 'HVAC Chesapeake'})
    assert result.status_code == 200
    assert result.json['places'][0]['attributions'][0]['provider'] == 'Example'
    assert call.call_args.kwargs['headers']['X-Goog-Api-Key'] == 'maps-test-secret'
    assert call.call_args.kwargs['allow_redirects'] is False


def test_people_does_not_silently_reuse_gmail_grant(client, monkeypatch):
    monkeypatch.delenv('GOOGLE_PEOPLE_REFRESH_TOKEN', raising=False)
    monkeypatch.setenv('GOOGLE_REFRESH_TOKEN', 'gmail-only-secret')
    call = Mock(side_effect=AssertionError('No People grant should make no Google calls'))
    monkeypatch.setattr(omni.requests, 'post', call)
    result = client.post('/api/chat/omniscope/people', headers=AUTH, json={})
    assert result.status_code == 503 and 'contacts.readonly' in result.json['error']
    assert not call.called


def test_ui_renders_provider_output_as_text_and_clears_context():
    source = Path('static/omniscope.js').read_text()
    assert '.innerHTML' not in source
    assert 'textContent=text' in source
    assert 'X-CSRF-Token' in source
    assert 'localStorage' not in source and 'sessionStorage' not in source


def test_live_research_returns_sources_without_claiming_verification(client, monkeypatch):
    import src.contact_sources as sources
    monkeypatch.setattr(sources, 'search', lambda query: {
        'results': [{'title': 'Public source', 'url': 'https://example.org/research',
                     'snippet': 'Supporting excerpt'}]})
    provider = Mock()
    provider.return_value.responses.create.return_value.output_text = 'Supported finding [1].'
    monkeypatch.setattr(omni, 'OpenAI', provider)
    result = client.post('/api/chat/omniscope/research', headers=AUTH,
                         json={'query': 'What do current sources say?'})
    assert result.status_code == 200
    assert result.json['sources'][0]['url'] == 'https://example.org/research'
    assert result.json['verified'] is False
    assert '[1]' in result.json['answer']
    assert provider.return_value.responses.create.call_args.kwargs['store'] is False


def test_live_research_rejects_invalid_input_before_provider(client, monkeypatch):
    import src.contact_sources as sources
    lookup = Mock(side_effect=AssertionError('No network call expected'))
    monkeypatch.setattr(sources, 'search', lookup)
    response = client.post('/api/chat/omniscope/research', headers=AUTH, json={'query': ' '})
    assert response.status_code == 400
    assert not lookup.called
