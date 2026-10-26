"""Resource ownership for the existing owner workspace and isolated customer reads.

Legacy rows belong to the existing single-owner deployment. New ownership is
recorded transactionally; customer sending stays disabled until mailbox isolation.
"""
import hashlib
import hmac
import os
import secrets
from urllib.parse import urlsplit
from flask import request, session, jsonify, has_request_context
from sqlalchemy import exists, and_, or_, cast, String, false
from app import app, db

OWNER='matthew-owner-workspace'

class ResourceOwnership(db.Model):
    __tablename__='resource_ownership'
    kind=db.Column(db.String(32),primary_key=True)
    resource_id=db.Column(db.String(64),primary_key=True)
    workspace_id=db.Column(db.String(96),nullable=False,index=True)

with app.app_context():db.create_all()


def current_workspace():
    if not has_request_context():return OWNER
    import outreach_automation as oa
    from customer_auth import google_session_authorized
    if google_session_authorized():
        email=session['google_identity']['email'].casefold()
        owner_emails={x.strip().casefold() for x in os.getenv('AUTOMAKE_WORKSPACE_OWNER_EMAILS','jolleyleads@gmail.com,neyolabs@gmail.com').split(',') if x.strip()}
        return OWNER if email in owner_emails else 'customer-'+hashlib.sha256(email.encode()).hexdigest()
    if oa._operator_authorized() or oa._operator_session_authorized():return OWNER
    return None


def research_workspace(create=False):
    workspace=current_workspace()
    if workspace:return workspace
    if create and not session.get('research_workspace'):
        session['research_workspace']='public-'+secrets.token_urlsafe(24)
    return session.get('research_workspace')


def claim(kind,resource_id,workspace):
    if not workspace:raise ValueError('Workspace required')
    key={'kind':kind,'resource_id':str(resource_id)}
    existing=db.session.get(ResourceOwnership,(kind,str(resource_id)))
    if existing and existing.workspace_id!=workspace:raise ValueError('Resource ownership conflict')
    if not existing:db.session.add(ResourceOwnership(**key,workspace_id=workspace))


def scope(model,kind,workspace=None):
    workspace=workspace or current_workspace()
    match=and_(ResourceOwnership.kind==kind,ResourceOwnership.resource_id==cast(model.id,String))
    assigned=exists().where(match,ResourceOwnership.workspace_id==workspace)
    if workspace==OWNER:
        return or_(assigned,~exists().where(match))
    return assigned if workspace else false()


def owns(kind,resource_id,workspace=None):
    workspace=workspace or current_workspace()
    row=db.session.get(ResourceOwnership,(kind,str(resource_id)))
    return bool(workspace and (row.workspace_id==workspace if row else workspace==OWNER))


def _deny(message,code=401):
    response=jsonify(ok=False,error=message)
    response.status_code=code;response.headers['Cache-Control']='no-store'
    return response


PUBLIC={'index','chat_operator_ui','customer_dashboard_script','customer_access_script','automake_logo',
        'login','customer_login','google_login','google_callback','customer_session','customer_logout',
        'chat_access','health','api_health','test_smart_search','create_research_job','get_research_job',
        'cancel_research_job','operator_login','static'}

@app.before_request
def protect_workspace_routes():
    if request.endpoint is None:return None
    endpoint=request.endpoint
    # Origin validation is additional to CSRF for browser requests.
    origin=request.headers.get('Origin')
    if request.method not in {'GET','HEAD','OPTIONS'} and origin:
        if urlsplit(origin).netloc!=request.host:
            return _deny('Cross-origin request rejected.',403)
    if endpoint in {'create_research_job','get_research_job','cancel_research_job'}:
        workspace=research_workspace(create=endpoint=='create_research_job')
        job_id=(request.view_args or {}).get('job_id')
        if job_id and not (owns('research',job_id,workspace) or (session.get('research_workspace') and owns('research',job_id,session['research_workspace']))):
            return _deny('Search not found.',404)
        return None
    if endpoint=='gmail_oauth_callback' and isinstance(session.get('google_login'),dict):return None
    if endpoint=='preview_selected_workflow':
        return None  # Read-only resolver checks lead ownership or this browser's research session.
    if endpoint in PUBLIC:return None
    if endpoint in {'process_followups','process_inbound_replies'}:
        return None  # Both routes independently require the canonical cron token.
    from src.acceptance_auth import acceptance_claims, request_key
    if endpoint in {'v11_acceptance_once','campaign_execution_status'}:
        claims=acceptance_claims()
        if claims:
            if endpoint=='v11_acceptance_once':
                if request.headers.get('Idempotency-Key')!=request_key(claims):return _deny('Invalid acceptance request binding.',403)
                return None
            from campaign_jobs import CampaignExecutionJob
            job=db.session.get(CampaignExecutionJob,(request.view_args or {}).get('job_id'))
            if job and job.kind=='acceptance' and job.request_key==request_key(claims):return None
            return _deny('Acceptance job not found.',404)
    workspace=current_workspace()
    if not workspace:return _deny('Sign in to access this workspace.')
    customer_read=endpoint in {'dashboard','lead_details','appointments','campaign_execution_status'}
    if workspace!=OWNER and not customer_read and endpoint not in {'salesforce_connect','salesforce_callback','salesforce_contacts'}:
        return _deny('This account has an isolated workspace. Sending and integrations require a separately connected mailbox.',403)
    import outreach_automation as oa
    if request.method not in {'GET','HEAD','OPTIONS'} and not oa._operator_authorized() and not oa._csrf_ok():
        return _deny('Invalid session request token.',403)
    if endpoint=='campaign_execution_status':
        job_id=(request.view_args or {}).get('job_id')
        if not owns('campaign',job_id,workspace):return _deny('Campaign not found.',404)
    if endpoint=='lead_details':
        if not owns('lead',(request.view_args or {}).get('lead_id'),workspace):return _deny('Lead not found.',404)
    return None
