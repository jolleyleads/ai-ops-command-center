"""Narrow GitHub OIDC trust for draft-only acceptance; no general operator access."""
import base64
import json
import os
import threading
import time
import requests
from google.auth import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from flask import request, g

ISSUER='https://token.actions.githubusercontent.com'
AUDIENCE='automakeai-production-acceptance'
REPOSITORY='jolleyleads/ai-ops-command-center'
WORKFLOW=REPOSITORY+'/.github/workflows/v11-production-acceptance.yml@refs/heads/main'
_cache={'expires':0,'certs':{}}
_lock=threading.Lock()


def _decode(value):return base64.urlsafe_b64decode(value+'='*(-len(value)%4))


def _certificates():
    with _lock:
        if _cache['expires']>time.monotonic():return _cache['certs']
        response=requests.get(ISSUER+'/.well-known/jwks',timeout=5)
        response.raise_for_status()
        certs={}
        for key in response.json().get('keys',[]):
            if key.get('kty')!='RSA' or key.get('alg') not in {None,'RS256'}:continue
            public=rsa.RSAPublicNumbers(int.from_bytes(_decode(key['e']),'big'),int.from_bytes(_decode(key['n']),'big')).public_key()
            certs[key['kid']]=public.public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
        _cache.update(certs=certs,expires=time.monotonic()+300)
        return certs


def acceptance_claims():
    if hasattr(g,'acceptance_claims'):return g.acceptance_claims
    g.acceptance_claims=None
    authorization=request.headers.get('Authorization','')
    if not authorization.startswith('Bearer '):return None
    token=authorization[7:]
    if len(token)>20000:return None
    try:
        header=json.loads(_decode(token.split('.')[0]))
        if header.get('alg')!='RS256':return None
        certs=_certificates()
        if header.get('kid') not in certs:return None
        claims=jwt.decode(token,certs=certs,audience=AUDIENCE,clock_skew_in_seconds=30)
        expected=os.getenv('RENDER_GIT_COMMIT','')
        now=time.time()
        valid=(claims.get('iss')==ISSUER and claims.get('repository')==REPOSITORY
               and str(claims.get('repository_id'))=='1237139816'
               and claims.get('ref')=='refs/heads/main' and claims.get('workflow_ref')==WORKFLOW
               and claims.get('event_name') in {'push','workflow_dispatch'}
               and claims.get('runner_environment')=='github-hosted'
               and bool(expected) and claims.get('sha')==expected
               and float(claims.get('nbf',0))<=now+30
               and 0<float(claims['exp'])-float(claims['iat'])<=900
               and str(claims.get('run_id','')).isdigit() and str(claims.get('run_attempt','')).isdigit())
        if valid:g.acceptance_claims=claims
    except Exception:
        return None
    return g.acceptance_claims


def request_key(claims):
    return 'acceptance-'+claims['sha']+'-'+str(claims['run_id'])+'-'+str(claims['run_attempt'])
