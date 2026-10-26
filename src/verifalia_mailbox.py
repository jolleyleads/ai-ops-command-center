"""Free-allowance-only Verifalia adapter, durable jobs and encrypted credentials."""
import base64
import hashlib
import json
import math
import os
import re
import time
import uuid
from datetime import datetime,timezone,timedelta

import requests
from cryptography.fernet import Fernet,InvalidToken
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from flask import has_app_context
from app import app,db

API='https://api.verifalia.com/v2.7'


class VerifaliaConnection(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    credentials=db.Column(db.Text,nullable=False)


class VerifaliaCheck(db.Model):
    key=db.Column(db.String(64),primary_key=True)
    state=db.Column(db.String(24),nullable=False)
    token=db.Column(db.String(64),nullable=False,default='')
    expires_at=db.Column(db.Float,nullable=False,default=0)
    receipt_json=db.Column(db.Text,nullable=False,default='{}')
    job_id=db.Column(db.String(36),nullable=False,default='')
    uses=db.Column(db.Integer,nullable=False,default=0)


with app.app_context():db.create_all()


def _cipher():
    secret=os.getenv('SECRET_KEY','')
    if len(secret)<32:raise ValueError('Secure credential storage is not configured.')
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(('verifalia-credentials-v1:'+secret).encode()).digest()))


def credentials():
    user=os.getenv('VERIFALIA_USERNAME','').strip();password=os.getenv('VERIFALIA_PASSWORD','')
    if user and password:return user,password
    if not has_app_context():return None
    try:
        with Session(db.engine) as session:
            row=session.get(VerifaliaConnection,1)
            if row:
                data=json.loads(_cipher().decrypt(row.credentials.encode()))
                return data['username'],data['password']
    except Exception:return None
    return None


def configured():
    # An unreadable saved connection must block, never silently select Hunter.
    if os.getenv('VERIFALIA_USERNAME') or os.getenv('VERIFALIA_PASSWORD'):return True
    if not has_app_context():return False
    try:
        with Session(db.engine) as session:return session.get(VerifaliaConnection,1) is not None
    except Exception:return True


def _number(value):return not isinstance(value,bool) and isinstance(value,(int,float)) and math.isfinite(value) and value>=0


def _request(method,path,auth,transport=None,**kwargs):
    response=(transport or requests.request)(method,API+path,auth=auth,timeout=(3,15),allow_redirects=False,**kwargs)
    if len(response.content)>100000:return {},0
    try:data=response.json()
    except ValueError:data={}
    return data if isinstance(data,dict) else {},response.status_code


def balance(auth=None,transport=None):
    auth=auth or credentials()
    if not auth:return {'ok':False,'state':'Not connected'}
    try:
        data,code=_request('GET','/credits/balance',auth,transport)
        if code in {401,403}:return {'ok':False,'state':'Check Verifalia credentials and API permissions'}
        if code!=200 or not _number(data.get('freeCredits')) or not _number(data.get('creditPacks')):
            return {'ok':False,'state':'Verifalia balance could not be confirmed'}
        if data['creditPacks']!=0:return {'ok':False,'state':'Free-only mode requires an account without paid credit packs'}
        identity=_hash(auth[0]+'\0'+auth[1])
        key=_hash('daily:'+identity+':'+datetime.now(timezone.utc).date().isoformat())
        with Session(db.engine) as session:
            row=session.get(VerifaliaCheck,key);remaining=min(int(data['freeCredits']),max(0,25-(row.uses if row else 0)))
        return {'ok':True,'state':'Connected' if remaining>=1 else 'Daily free allowance used',
                'free_remaining':remaining,'reset_in':str(data.get('freeCreditsResetIn') or '')[:20]}
    except Exception:return {'ok':False,'state':'Verifalia connection unavailable'}


def save_credentials(user,password):
    encrypted=_cipher().encrypt(json.dumps({'username':user,'password':password}).encode()).decode()
    row=db.session.get(VerifaliaConnection,1)
    if row:row.credentials=encrypted
    else:db.session.add(VerifaliaConnection(id=1,credentials=encrypted))
    db.session.commit()


def receipt(email,reason):
    return {'email':email,'provider':'verifalia','checked_at':datetime.now(timezone.utc).isoformat(),
            'mailbox_status':'unconfirmed','deliverability_status':'unconfirmed','reason_codes':[reason] if reason else []}


def normalize(email,data):
    result=receipt(email,'VERIFALIA_RESULT_UNCONFIRMED')
    overview=data.get('overview') or {};entries=data.get('entries') or {}
    items=entries.get('data') if isinstance(entries,dict) else None
    if (not isinstance(overview,dict) or overview.get('status')!='Completed' or not isinstance(items,list) or len(items)!=1):return result
    item=items[0]
    if not isinstance(item,dict) or str(item.get('inputData') or '').casefold()!=email.casefold():
        result['reason_codes']=['VERIFALIA_RESPONSE_EMAIL_MISMATCH'];return result
    from src.mailbox_verification import timestamp,MAX_AGE
    completed=timestamp(overview.get('completedOn'));now=datetime.now(timezone.utc)
    if not completed or not timedelta(0)<=now-completed<=MAX_AGE:
        result['reason_codes']=['MAILBOX_VERIFICATION_EXPIRED'];return result
    result['provider_verified_on']=completed.isoformat()
    result['provider_status']=str(item.get('status') or '')[:80]
    # Classification is account-customizable. Require the raw Success status too.
    if item.get('status')=='Success' and item.get('classification')=='Deliverable' and item.get('isDisposableEmailAddress') is not True:
        result.update(mailbox_status='provider_verified',deliverability_status='provider_reported_valid',reason_codes=[])
    elif item.get('classification')=='Undeliverable':
        result.update(mailbox_status='provider_rejected',reason_codes=['VERIFALIA_ADDRESS_REJECTED'])
    return result


def _hash(value):return hashlib.sha256(value.encode()).hexdigest()


def _claim(key,token,now):
    try:
        with Session(db.engine) as session:
            row=session.get(VerifaliaCheck,key)
            if row:
                if row.expires_at>now:return None,json.loads(row.receipt_json)
                changed=session.execute(update(VerifaliaCheck).where(VerifaliaCheck.key==key,VerifaliaCheck.expires_at<=now).values(token=token,expires_at=now+120)).rowcount
                if not changed:return None,{}
                job=row.job_id
            else:
                session.add(VerifaliaCheck(key=key,state='reserved',token=token,expires_at=now+120))
                job=''
            session.commit();return job,None
    except IntegrityError:return None,{}


def _save(key,token,result,job='',ttl=60):
    with Session(db.engine) as session:
        changed=session.execute(update(VerifaliaCheck).where(VerifaliaCheck.key==key,VerifaliaCheck.token==token).values(
            state='complete',expires_at=time.time()+ttl,receipt_json=json.dumps(result),job_id=job)).rowcount
        session.commit()
        if changed!=1:raise ValueError('Verification lease expired')


def _reserve_daily(identity):
    key=_hash('daily:'+identity+':'+datetime.now(timezone.utc).date().isoformat())
    with Session(db.engine) as session:
        row=session.get(VerifaliaCheck,key)
        if row:
            changed=session.execute(update(VerifaliaCheck).where(VerifaliaCheck.key==key,VerifaliaCheck.uses<25).values(uses=VerifaliaCheck.uses+1)).rowcount
            if not changed:return False
        else:session.add(VerifaliaCheck(key=key,state='allowance',uses=1))
        session.commit();return True


def verify(email,transport=None):
    email=str(email or '').strip().lower();auth=credentials()
    if not auth:return receipt(email,'VERIFALIA_NOT_CONNECTED')
    if not has_app_context():return receipt(email,'VERIFALIA_CACHE_UNAVAILABLE')
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):return receipt(email,'VERIFALIA_ADDRESS_REJECTED')
    identity=_hash(auth[0]+'\0'+auth[1]);key=_hash('mailbox:'+identity+':'+email);token=uuid.uuid4().hex
    result=receipt(email,'VERIFALIA_PROVIDER_UNAVAILABLE');job='';post_started=False
    try:
        job,cached=_claim(key,token,time.time())
        if cached is not None:return {**cached,'cache_hit':True} if cached else receipt(email,'VERIFALIA_CHECK_IN_PROGRESS')
        if job:
            data,code=_request('GET','/email-validations/'+job,auth,transport,params={'waitTime':5000})
        else:
            account_key=_hash('account:'+identity);account_token=uuid.uuid4().hex
            _,blocked=_claim(account_key,account_token,time.time())
            if blocked is not None:
                result=receipt(email,'VERIFALIA_CHECK_IN_PROGRESS');_save(key,token,result,ttl=5);return result
            try:
                funds=balance(auth,transport)
                if not funds.get('ok'):
                    result=receipt(email,'VERIFALIA_ACCOUNT_CHECK_FAILED');_save(key,token,result);return result
                if funds['free_remaining']<1 or not _reserve_daily(identity):
                    result=receipt(email,'VERIFALIA_FREE_QUOTA_EXHAUSTED')
                    _save(key,token,result,ttl=60);return result
                # Fixed Standard quality, one address, no credit purchase or paid fallback.
                # Reserve before POST: a lost response must never automatically resubmit.
                post_started=True
                _save(key,token,receipt(email,'VERIFALIA_SUBMISSION_UNCONFIRMED'),ttl=86400)
                data,code=_request('POST','/email-validations',auth,transport,params={'waitTime':5000},
                                   json={'entries':[{'inputData':email}],'quality':'Standard'})
            finally:_save(account_key,account_token,{},ttl=0)
        if code==202:
            candidate=str((data.get('overview') or {}).get('id') or '')
            if not re.fullmatch(r'[0-9a-fA-F-]{36}',candidate):
                result=receipt(email,'VERIFALIA_SUBMISSION_UNCONFIRMED');_save(key,token,result,ttl=86400);return result
            job=str(uuid.UUID(candidate));result=receipt(email,'VERIFALIA_RESULT_PENDING')
            _save(key,token,result,job,ttl=5);return result
        if code==200:result=normalize(email,data)
        elif code==402:result=receipt(email,'VERIFALIA_FREE_QUOTA_EXHAUSTED')
        elif code in {401,403}:result=receipt(email,'VERIFALIA_ACCOUNT_CHECK_FAILED')
        else:result=receipt(email,'VERIFALIA_SUBMISSION_UNCONFIRMED' if post_started else 'VERIFALIA_PROVIDER_UNAVAILABLE')
        from src.mailbox_verification import timestamp,MAX_AGE
        if result['mailbox_status']=='provider_verified':
            ttl=max(0,(timestamp(result['provider_verified_on'])+MAX_AGE-datetime.now(timezone.utc)).total_seconds())
        else:ttl=86400 if code==200 or (post_started and code not in {401,402,403}) else 60
        _save(key,token,result,job if code!=200 else '',ttl=ttl);return result
    except Exception:
        # Never return exception text, credentials, or provider headers.
        result=receipt(email,'VERIFALIA_SUBMISSION_UNCONFIRMED' if post_started else 'VERIFALIA_PROVIDER_UNAVAILABLE')
        try:_save(key,token,result,job,ttl=86400 if post_started and not job else 60)
        except Exception:pass
        return result
