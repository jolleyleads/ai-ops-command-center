"""Google sign-in for explicitly approved users of the existing shared workspace.

Identity login requests no Gmail or Calendar permissions and makes no DB changes.
"""
import base64
import hashlib
import hmac
import os
import secrets
import time
from urllib.parse import urlencode, urlsplit

import requests
from flask import redirect, render_template, request, session
from google.auth.transport.requests import Request
from google.auth.exceptions import GoogleAuthError
from google.oauth2.id_token import verify_oauth2_token

from app import app

LOGIN_TTL = 600
SESSION_TTL = 8 * 60 * 60


def allowed_emails():
    return {x.strip().casefold() for x in os.getenv('GOOGLE_LOGIN_ALLOWED_EMAILS', '').split(',') if x.strip()}


def credentials():
    return (os.getenv('GOOGLE_LOGIN_CLIENT_ID') or os.getenv('GOOGLE_CLIENT_ID', ''),
            os.getenv('GOOGLE_LOGIN_CLIENT_SECRET') or os.getenv('GOOGLE_CLIENT_SECRET', ''))


def callback_uri():
    return os.getenv('GOOGLE_LOGIN_REDIRECT_URI', 'https://automakeai.live/auth/google/callback')


def configured():
    uri = urlsplit(callback_uri())
    return bool(all(credentials()) and allowed_emails() and
                uri.scheme == 'https' and uri.netloc and not uri.query and not uri.fragment and
                app.secret_key and app.secret_key != 'dev-secret-key')


def _proof(identity):
    from outreach_automation import _session_proof
    key = _session_proof()
    if not key:
        return ''
    data = '\0'.join(str(identity.get(k, '')) for k in ('sub', 'email', 'expires'))
    return hmac.new(key.encode(), data.encode(), hashlib.sha256).hexdigest()


def google_session_authorized():
    identity = session.get('google_identity')
    if not isinstance(identity, dict) or not configured():
        return False
    try:
        expires = int(identity.get('expires', 0))
    except (TypeError, ValueError):
        return False
    expected = _proof(identity)
    return bool(identity.get('sub') and identity.get('email') in allowed_emails() and
                time.time() < expires <= time.time() + SESSION_TTL and expected and
                hmac.compare_digest(expected, str(identity.get('proof', ''))))


def login_page(error='', status=200):
    return render_template('customer_login.html', error=error, configured=configured()), status


def customer_login():
    from outreach_automation import _operator_session_authorized
    if _operator_session_authorized():
        return redirect('/chat-operator', 303)
    return login_page()


@app.get('/auth/google')
def google_login():
    if not configured():
        return login_page('Google sign-in is being set up. Please contact the workspace owner.', 503)
    # Start on the registered callback origin, keeping the host-only cookie on one
    # origin throughout login. Never trust a request Host header for redirects.
    callback = urlsplit(callback_uri())
    origin = f'{callback.scheme}://{callback.netloc}'
    if request.host_url.rstrip('/') != origin:
        return redirect(origin + '/auth/google', 303)
    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    session['google_login'] = {'state': state, 'nonce': nonce, 'verifier': verifier, 'issued': time.time()}
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    params = {'client_id': credentials()[0], 'redirect_uri': callback_uri(),
              'response_type': 'code', 'scope': 'openid email', 'state': state,
              'nonce': nonce, 'prompt': 'select_account',
              'code_challenge': challenge, 'code_challenge_method': 'S256'}
    return redirect('https://accounts.google.com/o/oauth2/v2/auth?' + urlencode(params))


@app.get('/auth/google/callback')
def google_callback():
    pending = session.pop('google_login', None)
    if not configured() or not isinstance(pending, dict):
        return login_page('Your sign-in expired. Please try again.', 400)
    age = time.time() - pending.get('issued', 0)
    if not 0 <= age <= LOGIN_TTL or not hmac.compare_digest(
            str(pending.get('state', '')), request.args.get('state', '')):
        return login_page('Your sign-in expired. Please try again.', 400)
    if request.args.get('error') or not request.args.get('code'):
        return login_page('Google sign-in was cancelled. You can try again.', 400)
    try:
        response = requests.post('https://oauth2.googleapis.com/token', data={
            'client_id': credentials()[0], 'client_secret': credentials()[1],
            'grant_type': 'authorization_code', 'code': request.args['code'],
            'redirect_uri': callback_uri(), 'code_verifier': pending['verifier'],
        }, timeout=15)
        response.raise_for_status()
        # Google's library verifies signature, issuer, audience and expiry.
        claims = verify_oauth2_token(response.json()['id_token'], Request(), credentials()[0])
        if not hmac.compare_digest(str(claims.get('nonce', '')), pending['nonce']):
            raise ValueError('Invalid nonce')
        email = str(claims.get('email', '')).casefold()
        if claims.get('email_verified') is not True or not claims.get('sub') or email not in allowed_emails():
            return login_page('This Google account does not have access to this workspace.', 403)
        identity = {'sub': str(claims['sub']), 'email': email, 'expires': int(time.time()) + SESSION_TTL}
        identity['proof'] = _proof(identity)
        if not identity['proof']:
            return login_page('Workspace access is not configured. Please contact the owner.', 503)
    except (requests.RequestException, GoogleAuthError, ValueError, KeyError, TypeError):
        return login_page('We could not complete Google sign-in. Please try again.', 502)
    session.clear()
    session['google_identity'] = identity
    session['csrf_token'] = secrets.token_urlsafe(32)
    session.permanent = True
    return redirect('/chat-operator', 303)


@app.get('/auth/session')
def customer_session():
    from outreach_automation import _operator_session_authorized, _csrf_token
    signed_in = _operator_session_authorized()
    return {'signed_in': signed_in, 'csrf_token': _csrf_token() if signed_in else None}


@app.post('/auth/logout')
def customer_logout():
    from outreach_automation import _csrf_ok
    if not _csrf_ok():
        return {'error': 'Please refresh the page and try again.'}, 403
    session.clear()
    return redirect('/login', 303)


@app.after_request
def protect_login_response(response):
    if request.path == '/login' or request.path.startswith('/auth/'):
        response.headers.update({'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
                                 'X-Frame-Options': 'DENY', 'X-Content-Type-Options': 'nosniff'})
    return response
