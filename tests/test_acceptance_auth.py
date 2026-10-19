import time
import json
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from google.auth import jwt, crypt
import commercial_app
import campaign_jobs as jobs
from src import acceptance_auth as auth

@pytest.fixture
def signing(monkeypatch):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    private=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
    public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
    monkeypatch.setattr(auth,'_certificates',lambda:{'test':public})
    monkeypatch.setenv('RENDER_GIT_COMMIT','deployed-sha')
    monkeypatch.setattr(jobs,'kick_execution_worker',lambda:None)
    now=int(time.time())
    claims={'iss':auth.ISSUER,'aud':auth.AUDIENCE,'repository':auth.REPOSITORY,'repository_id':'1237139816',
        'ref':'refs/heads/main','workflow_ref':auth.WORKFLOW,'event_name':'push','runner_environment':'github-hosted',
        'sha':'deployed-sha','iat':now,'nbf':now,'exp':now+300,'run_id':'123','run_attempt':'1'}
    def token(**overrides):
        return jwt.encode(crypt.RSASigner.from_string(private,key_id='test'),{**claims,**overrides}).decode()
    with jobs.app.app_context():
        jobs.db.drop_all();jobs.db.create_all()
        yield jobs.app.test_client(),claims,token
        jobs.db.session.remove();jobs.db.drop_all()


def test_signed_workflow_can_only_start_and_poll_its_bound_acceptance(signing):
    client,claims,token=signing
    headers={'Authorization':'Bearer '+token(),'Idempotency-Key':auth.request_key(claims)}
    response=client.post('/api/operator/v1-1-acceptance-once',headers=headers)
    assert response.status_code==202
    assert client.get(response.json['poll_url'],headers=headers).status_code==200
    assert client.get('/api/chat/dashboard',headers=headers).status_code==401
    assert client.get('/api/demo/campaigns/jobs/another',headers=headers).status_code==404
    assert client.post('/api/chat/campaigns/launch',json={},headers=headers).status_code==401
    assert client.post('/api/operator/v1-1-acceptance-once',headers={**headers,'Idempotency-Key':'different'}).status_code==403


@pytest.mark.parametrize('overrides',[
    {'repository':'attacker/project'},{'repository_id':'999'}, {'ref':'refs/heads/feature'},
    {'workflow_ref':auth.REPOSITORY+'/.github/workflows/other.yml@refs/heads/main'},
    {'sha':'old-sha'},{'aud':'other'},{'event_name':'pull_request'},
    {'exp':1,'iat':0},{'nbf':9999999999}, {'runner_environment':'self-hosted'}])
def test_workflow_claim_restrictions_fail_closed(signing,overrides):
    client,claims,token=signing
    response=client.post('/api/operator/v1-1-acceptance-once',headers={'Authorization':'Bearer '+token(**overrides),'Idempotency-Key':auth.request_key(claims)})
    assert response.status_code==401
    assert jobs.CampaignExecutionJob.query.count()==0


def test_signature_tampering_is_rejected(signing):
    client,claims,token=signing
    encoded=token();parts=encoded.split('.')
    parts[1]=parts[1][:-3]+'abc'
    assert client.post('/api/operator/v1-1-acceptance-once',headers={'Authorization':'Bearer '+'.'.join(parts),'Idempotency-Key':auth.request_key(claims)}).status_code==401
