"""One operator-configured production campaign, submitted with a durable run ID.

Only trusted service configuration can authorize this path. No public route can
set the authorization bit. Leaving the configuration in place cannot replay it.
"""
import json
import os
from app import app


def start_configured_campaign():
    run_id=os.getenv('AUTOMAKE_CAMPAIGN_RUN_ID','').strip()
    raw=os.getenv('AUTOMAKE_CAMPAIGN_REQUEST','').strip()
    if not run_id or not raw:return
    app.logger.warning('CAMPAIGN_PROVIDER_CONFIGURATION openai=%s exa=%s hunter=%s hunter_verification_enabled=%s hunter_account=%s',bool(os.getenv('OPENAI_API_KEY')),bool(os.getenv('EXA_API_KEY')),bool(os.getenv('HUNTER_API_KEY')),os.getenv('HUNTER_MAILBOX_VERIFICATION_ENABLED','false'),os.getenv('HUNTER_ACCOUNT_EMAIL','missing'))
    from customer_demo import _campaign_payload
    from campaign_jobs import enqueue_execution
    try:
        data=json.loads(raw)
        if not isinstance(data,dict):raise ValueError('invalid campaign')
        payload,error=_campaign_payload(data)
        if error:raise ValueError('invalid campaign')
        payload['send_authorized']=os.getenv('AUTOMAKE_CAMPAIGN_SEND','0')=='1'
        payload['require_decision_maker']=data.get('require_decision_maker') is True
        with app.app_context():
            response=app.make_response(enqueue_execution('campaign',payload,'configured-campaign-'+run_id[:100]))
            result=response.get_json()
            app.logger.warning('CONFIGURED_CAMPAIGN_SUBMITTED job_id=%s status=%s',result.get('job_id'),result.get('status'))
    except Exception as exc:
        # Configurations and exception messages may contain private offer text.
        app.logger.error('CONFIGURED_CAMPAIGN_SETUP_FAILED type=%s',type(exc).__name__)
