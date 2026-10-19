import time
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock

import pytest
import commercial_app
import customer_auth as auth
import outreach_automation as oa


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('OPERATOR_CONTROL_TOKEN', 'test-operator-secret')
    monkeypatch.setenv('GOOGLE_LOGIN_CLIENT_ID', 'client.apps.googleusercontent.com')
    monkeypatch.setenv('GOOGLE_LOGIN_CLIENT_SECRET', 'test-client-secret')
    monkeypatch.setenv('GOOGLE_LOGIN_ALLOWED_EMAILS', 'owner@example.com')
    monkeypatch.setenv('GOOGLE_LOGIN_REDIRECT_URI', 'https://automakeai.live/auth/google/callback')
    monkeypatch.setattr(oa.app, 'secret_key', 'a-secure-test-session-secret')
    return oa.app.test_client()


def start(client):
    response = client.get('/auth/google', base_url='https://automakeai.live')
    assert response.status_code == 302
    query = parse_qs(urlsplit(response.location).query)
    assert query['scope'] == ['openid email']
    assert query['code_challenge_method'] == ['S256']
    with client.session_transaction(base_url='https://automakeai.live') as session:
        pending = dict(session['google_login'])
    return pending


def callback(client, pending):
    return client.get('/auth/google/callback', query_string={'state': pending['state'], 'code': 'test-code'},
                      base_url='https://automakeai.live')


def mock_google(monkeypatch, pending, **override):
    response = Mock()
    response.json.return_value = {'id_token': 'mock-identity-token'}
    post = Mock(return_value=response)
    monkeypatch.setattr(auth.requests, 'post', post)
    claims = {'sub': 'subject-123', 'email': 'owner@example.com', 'email_verified': True,
              'nonce': pending['nonce']}
    claims.update(override)
    verify = Mock(return_value=claims)
    monkeypatch.setattr(auth, 'verify_oauth2_token', verify)
    return post, verify


def test_login_has_google_button_and_no_operator_token(client):
    response = client.get('/login')
    assert b'Continue with Google' in response.data
    assert b'Operator token' not in response.data
    assert response.headers['Cache-Control'] == 'no-store'
    assert client.get('/operator/login').location == '/login'
    assert client.get('/api/chat/dashboard').status_code == 401


def test_missing_configuration_fails_closed(client, monkeypatch):
    monkeypatch.delenv('GOOGLE_LOGIN_ALLOWED_EMAILS')
    assert client.get('/auth/google').status_code == 503
    assert client.get('/auth/session').json['signed_in'] is False


def test_start_uses_registered_host_not_host_header(client):
    response = client.get('/auth/google', base_url='https://attacker.example')
    assert response.location == 'https://automakeai.live/auth/google'


@pytest.mark.parametrize('failure', ['state', 'expired', 'cancelled'])
def test_reject_invalid_callback_before_contacting_google(client, monkeypatch, failure):
    pending = start(client)
    post = Mock(side_effect=AssertionError('Google must not be called'))
    monkeypatch.setattr(auth.requests, 'post', post)
    if failure == 'state':
        pending['state'] = 'wrong-state'
    elif failure == 'expired':
        with client.session_transaction(base_url='https://automakeai.live') as session:
            data = dict(session['google_login']);data['issued'] = time.time() - 700;session['google_login'] = data
    if failure == 'cancelled':
        response = client.get('/auth/google/callback', query_string={'state': pending['state'], 'error': 'access_denied'}, base_url='https://automakeai.live')
    else:
        response = callback(client, pending)
    assert response.status_code == 400
    assert post.call_count == 0


@pytest.mark.parametrize('claims,status', [({'email': 'outsider@example.com'},403),
    ({'email_verified': False},403), ({'sub': ''},403), ({'nonce':'wrong'},502)])
def test_reject_unapproved_or_invalid_identities(client, monkeypatch, claims, status):
    pending = start(client)
    mock_google(monkeypatch, pending, **claims)
    assert callback(client, pending).status_code == status
    assert client.get('/auth/session', base_url='https://automakeai.live').json['signed_in'] is False


def test_sign_in_session_replay_logout_and_revocation(client, monkeypatch):
    pending = start(client)
    post, verify = mock_google(monkeypatch, pending)
    result = callback(client, pending)
    assert result.status_code == 303 and result.location == '/chat-operator'
    assert verify.call_args.args[2] == 'client.apps.googleusercontent.com'
    assert post.call_args.kwargs['data']['code_verifier'] == pending['verifier']
    cookie = result.headers['Set-Cookie']
    assert 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=Lax' in cookie
    state = client.get('/auth/session', base_url='https://automakeai.live').json
    assert state['signed_in'] and state['csrf_token']
    assert callback(client, pending).status_code == 400  # consumed state
    assert client.post('/auth/logout', base_url='https://automakeai.live').status_code == 403
    monkeypatch.setenv('GOOGLE_LOGIN_ALLOWED_EMAILS', 'another@example.com')
    assert not client.get('/auth/session', base_url='https://automakeai.live').json['signed_in']
    monkeypatch.setenv('GOOGLE_LOGIN_ALLOWED_EMAILS', 'owner@example.com')
    assert client.post('/auth/logout', data={'csrf_token':state['csrf_token']}, base_url='https://automakeai.live').status_code == 303
    assert not client.get('/auth/session', base_url='https://automakeai.live').json['signed_in']


def test_identity_cannot_be_forged_from_public_session_key(client):
    with client.session_transaction(base_url='https://automakeai.live') as session:
        session['google_identity'] = {'sub':'fake', 'email':'owner@example.com',
                                     'expires':int(time.time())+100, 'proof':'invented'}
    assert not client.get('/auth/session', base_url='https://automakeai.live').json['signed_in']


def test_token_verification_failure_never_creates_session(client, monkeypatch):
    pending = start(client)
    mock_google(monkeypatch, pending)
    monkeypatch.setattr(auth, 'verify_oauth2_token', Mock(side_effect=ValueError('bad signature')))
    assert callback(client, pending).status_code == 502
    assert not client.get('/auth/session', base_url='https://automakeai.live').json['signed_in']


def test_existing_google_callback_supports_identity_without_touching_gmail(client, monkeypatch):
    import gmail_connect
    origin = 'https://ai-ops-command-center.onrender.com'
    uri = origin + '/oauth/google/callback'
    monkeypatch.setenv('GOOGLE_LOGIN_REDIRECT_URI', uri)
    initial = client.get('/auth/google', base_url='https://automakeai.live')
    assert initial.location == origin + '/auth/google'
    response = client.get('/auth/google', base_url=origin)
    assert parse_qs(urlsplit(response.location).query)['redirect_uri'] == [uri]
    with client.session_transaction(base_url=origin) as session:
        pending = dict(session['google_login'])
    post, verify = mock_google(monkeypatch, pending)
    monkeypatch.setattr(gmail_connect, '_valid_state', Mock(side_effect=AssertionError('Mailbox callback must not run')))
    result = client.get('/oauth/google/callback', query_string={'state':pending['state'],'code':'test-code'}, base_url=origin)
    assert result.status_code == 303 and result.location == '/chat-operator'
    assert post.call_args.kwargs['data']['redirect_uri'] == uri
    assert client.get('/auth/session', base_url=origin).json['signed_in']


def test_nonmatching_identity_state_cannot_enter_shared_callback(client, monkeypatch):
    import gmail_connect
    pending = start(client)
    monkeypatch.setattr(gmail_connect, '_valid_state', lambda value:False)
    post = Mock(side_effect=AssertionError('No token exchange permitted'))
    monkeypatch.setattr(auth.requests, 'post', post)
    result = client.get('/oauth/google/callback', query_string={'state':'wrong','code':'test-code'}, base_url='https://automakeai.live')
    assert result.status_code == 400 and post.call_count == 0


def test_public_access_hint_and_pending_request_preservation(client):
    response=client.get('/api/chat/access')
    assert response.status_code==200 and response.json['signed_in'] is False
    assert response.json['research_available'] is True
    assert response.headers['Cache-Control']=='no-store'
    assert 'csrf_token' not in response.json
    assert client.get('/api/chat/dashboard').status_code==401
    page=client.get('/chat-operator').text
    assert '/chat-operator/access.js' in page
    script=client.get('/chat-operator/access.js').text
    assert 'sessionStorage' in script and 'automake-pending-prompt' in script
    assert 'campaign.disabled=!access.signed_in' in script
