"""Opt-in Hunter verifier, with a durable lease and free-account guard."""
import hashlib
import json
import math
import os
import time
import uuid
from datetime import datetime, timezone, timedelta
import requests
from flask import has_app_context
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app import db


class HunterMailboxCheck(db.Model):
    __tablename__ = 'hunter_mailbox_check'
    key = db.Column(db.String(64), primary_key=True)
    state = db.Column(db.String(20), nullable=False)
    lease_token = db.Column(db.String(64), nullable=False)
    expires_at = db.Column(db.Float, nullable=False)
    receipt_json = db.Column(db.Text, nullable=False, default='{}')


def enabled():
    return os.getenv('HUNTER_MAILBOX_VERIFICATION_ENABLED','false').lower()=='true'


def base_receipt(email,reason):
    return {'email':email,'provider':'hunter','checked_at':datetime.now(timezone.utc).isoformat(),'mailbox_status':'unconfirmed','deliverability_status':'unconfirmed','reason_codes':[reason]}


def _restriction_key(email):
    return hashlib.sha256(('hunter-processing-restricted:'+str(email).strip().lower()).encode()).hexdigest()


def processing_restricted(email):
    if not has_app_context():return False
    try:
        with Session(db.engine) as session:
            row=session.get(HunterMailboxCheck,_restriction_key(email))
            return bool(row and row.state=='restricted')
    except Exception:return False


def normalize_result(email,data,now=None):
    receipt=base_receipt(email,'HUNTER_RESULT_UNCONFIRMED')
    if not isinstance(data,dict) or str(data.get('email') or '').lower()!=email.lower():
        receipt['reason_codes']=['HUNTER_RESPONSE_EMAIL_MISMATCH'];return receipt
    status=data.get('status')
    receipt['provider_status']=status if status in {'valid','invalid','accept_all','webmail','disposable','unknown'} else 'unknown'
    verification=data.get('verification') or {}
    if not isinstance(verification,dict):return receipt
    date=verification.get('date')
    receipt['provider_verified_on']=date if isinstance(date,str) and len(date)<=30 else None
    if status=='accept_all' or data.get('accept_all') is True:
        receipt['reason_codes']=['HUNTER_ACCEPT_ALL_UNCONFIRMED'];return receipt
    if status in {'invalid','disposable'}:
        receipt['mailbox_status']='provider_rejected';receipt['reason_codes']=['HUNTER_ADDRESS_REJECTED'];return receipt
    now=now or datetime.now(timezone.utc)
    try:
        verified=datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
        fresh=now-timedelta(days=7)<=verified<=now
    except (ValueError,TypeError):fresh=False
    if status=='valid' and verification.get('status')=='valid' and data.get('smtp_check') is True and data.get('accept_all') is False and data.get('block') is False and data.get('disposable') is False and fresh:
        receipt.update(mailbox_status='provider_verified',deliverability_status='provider_reported_valid',reason_codes=[])
    elif not fresh:receipt['reason_codes']=['HUNTER_RESULT_DATE_UNCONFIRMED_OR_STALE']
    return receipt


def _request(path,key,params,get):
    response=get('https://api.hunter.io/v2/'+path,headers={'X-API-KEY':key},params=params,timeout=(2,22),allow_redirects=False)
    if response.status_code!=200:return None,response.status_code
    if len(response.content)>100000:return None,0
    body=response.json()
    if not isinstance(body,dict) or body.get('errors'):return None,0
    return body.get('data'),200


def verify_mailbox(email,get=None):
    email=str(email or '').strip().lower()
    if processing_restricted(email):
        receipt=base_receipt(email,'HUNTER_PROCESSING_RESTRICTED');receipt['mailbox_status']='provider_rejected';return receipt
    if not enabled():return base_receipt(email,'HUNTER_NOT_ENABLED')
    key=os.getenv('HUNTER_API_KEY','').strip()
    expected=os.getenv('HUNTER_ACCOUNT_EMAIL','').strip().lower()
    if not key or key=='test-api-key':return base_receipt(email,'HUNTER_REAL_CREDENTIAL_REQUIRED')
    if not expected:return base_receipt(email,'HUNTER_ACCOUNT_EMAIL_REQUIRED')
    if not has_app_context():return base_receipt(email,'HUNTER_CACHE_UNAVAILABLE')
    cache_key=hashlib.sha256(('hunter:'+hashlib.sha256(key.encode()).hexdigest()+':'+expected+':'+email).encode()).hexdigest()
    now=time.time()
    token=uuid.uuid4().hex
    # Separate transaction: never commit/roll back the caller's lead workflow.
    try:
        with Session(db.engine) as session:
            row=session.get(HunterMailboxCheck,cache_key)
            if row and row.expires_at>now:
                if row.state=='complete':
                    result=json.loads(row.receipt_json);result['cache_hit']=True;return result
                return base_receipt(email,'HUNTER_CHECK_IN_PROGRESS')
            if row:
                claimed=session.execute(update(HunterMailboxCheck).where(HunterMailboxCheck.key==cache_key,HunterMailboxCheck.expires_at<=now).values(state='reserved',lease_token=token,expires_at=now+120,receipt_json='{}')).rowcount
                if not claimed:return base_receipt(email,'HUNTER_CHECK_IN_PROGRESS')
            else:session.add(HunterMailboxCheck(key=cache_key,state='reserved',lease_token=token,expires_at=now+120,receipt_json='{}'))
            session.commit()
    except IntegrityError:return base_receipt(email,'HUNTER_CHECK_IN_PROGRESS')
    except Exception:return base_receipt(email,'HUNTER_CACHE_UNAVAILABLE')
    receipt=base_receipt(email,'HUNTER_PROVIDER_UNAVAILABLE')
    try:
        get=get or requests.get
        account,code=_request('account',key,{},get)
        if not isinstance(account,dict):receipt['reason_codes']=['HUNTER_ACCOUNT_CHECK_FAILED']
        elif str(account.get('email') or '').lower()!=expected:receipt['reason_codes']=['HUNTER_ACCOUNT_MISMATCH']
        elif str(account.get('plan_name') or '').lower()!='free':receipt['reason_codes']=['HUNTER_FREE_PLAN_REQUIRED']
        else:
            requests_left=account.get('requests') or {}
            credits=requests_left.get('credits')
            bucket=credits if isinstance(credits,dict) else requests_left.get('verifications') or {}
            remaining=bucket.get('remaining')
            if isinstance(remaining,bool) or not isinstance(remaining,(int,float)) or not math.isfinite(remaining) or remaining<(0.5 if isinstance(credits,dict) else 1):
                receipt['reason_codes']=['HUNTER_FREE_QUOTA_UNAVAILABLE']
            else:
                data,code=_request('email-verifier',key,{'email':email},get)
                if code==202:receipt['reason_codes']=['HUNTER_RESULT_PENDING']
                elif code==429:receipt['reason_codes']=['HUNTER_FREE_QUOTA_EXHAUSTED']
                elif code==451:
                    receipt.update(mailbox_status='provider_rejected',reason_codes=['HUNTER_PROCESSING_RESTRICTED'])
                elif code==200:receipt=normalize_result(email,data)
    except Exception:
        # Never persist exception text: HTTP exceptions can contain credentials.
        receipt=base_receipt(email,'HUNTER_PROVIDER_UNAVAILABLE')
    ttl=60
    if receipt['mailbox_status']=='provider_verified':
        verified=datetime.fromisoformat(receipt['provider_verified_on']).replace(tzinfo=timezone.utc)
        ttl=max(0,min(86400,(verified+timedelta(days=7)).timestamp()-time.time()))
    try:
        with Session(db.engine) as session:
            completed=session.execute(update(HunterMailboxCheck).where(HunterMailboxCheck.key==cache_key,HunterMailboxCheck.state=='reserved',HunterMailboxCheck.lease_token==token).values(state='complete',expires_at=time.time()+ttl,receipt_json=json.dumps(receipt))).rowcount
            if completed!=1:return base_receipt(email,'HUNTER_RECEIPT_STORAGE_FAILED')
            if receipt['reason_codes']==['HUNTER_PROCESSING_RESTRICTED']:
                restriction=_restriction_key(email)
                if session.get(HunterMailboxCheck,restriction) is None:
                    session.add(HunterMailboxCheck(key=restriction,state='restricted',lease_token='restricted',expires_at=0,receipt_json='{}'))
            session.commit()
    except Exception:return base_receipt(email,'HUNTER_RECEIPT_STORAGE_FAILED')
    return receipt


def apply_mailbox_check(enrichment):
    record=enrichment.get('fields',{}).get('email')
    if not record or record.get('validated') is not True:return enrichment
    receipt=verify_mailbox(record['value'])
    assessment=enrichment.setdefault('contact_assessment',{})
    assessment['mailbox_validation']=receipt
    record['mailbox_status']=receipt['mailbox_status']
    record['deliverability_status']=receipt['deliverability_status']
    if (enabled() and receipt['mailbox_status']!='provider_verified') or receipt['reason_codes']==['HUNTER_PROCESSING_RESTRICTED']:
        record['validated']=False
        assessment.setdefault('reason_codes',[]).append('INDEPENDENT_MAILBOX_VERIFICATION_REQUIRED')
    return enrichment
