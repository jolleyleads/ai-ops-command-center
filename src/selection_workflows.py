"""Explicit one-business workflow grants, run by the existing durable job worker."""
import copy
import hashlib
import json
from datetime import datetime, timedelta
from flask import jsonify, request, session
from app import app, db
import outreach_automation as oa
from campaign_jobs import CampaignExecutionJob, enqueue_execution, _view
from workspace_security import OWNER, current_workspace, owns, scope
from src.selection_refs import business_key
from src.company_identity import name_key, owned_host


def _unpack(value):
    try:return json.loads(value or '{}')
    except (TypeError,ValueError):return {}


def resolve_selection(ref):
    """Return only a persisted resource owned by this account/browser."""
    kind=ref.get('kind')
    if kind=='lead':
        key=ref.get('lead_id')
        if type(key) is not int or not owns('lead',key):return None
        lead=db.session.get(oa.OutreachLead,key)
        if not lead:return None
        context=oa._server_qualification_inputs(lead)[1]
        return {'company':lead.company,'website':lead.source_url,'source_url':lead.source_url,'location':lead.location},context.get('query') or 'Find businesses',context.get('target_location') or lead.location,lead.id
    job_id=ref.get('job_id');key=ref.get('key')
    if not isinstance(job_id,str) or not isinstance(key,str):return None
    if kind=='research':
        from background_research import ResearchJob
        public=session.get('research_workspace')
        if not (owns('research',job_id) or (public and owns('research',job_id,public))):return None
        job=db.session.get(ResearchJob,job_id)
        if not job:return None
        saved=_unpack(job.result_json);progress=saved.get('progress') or {}
        rows=(saved.get('results') or [])+(progress.get('businesses') or [])+(progress.get('candidates') or [])
        query=job.prompt_text;location=job.location
    elif kind=='campaign':
        if not owns('campaign',job_id):return None
        job=db.session.get(CampaignExecutionJob,job_id)
        if not job:return None
        from src.progressive_campaign import CampaignBusinessTask
        # Prefer the durable full business row over a display-only projection.
        rows=[_unpack(x.business_json) for x in CampaignBusinessTask.query.filter_by(campaign_id=job_id).all()]
        saved=_unpack(job.result_json);progress=saved.get('progress') or {};payload=_unpack(job.payload_json)
        rows+=(saved.get('discovery') or {}).get('results') or []
        rows+=(progress.get('businesses') or [])+(progress.get('candidates') or [])
        query=payload.get('query') or payload.get('target_customer') or '';location=payload.get('territory') or ''
    else:return None
    row=next((x for x in rows if isinstance(x,dict) and business_key(x)==key),None)
    return (copy.deepcopy(row),query,location,None) if row else None


@app.post('/api/chat/workflows/activate')
def activate_selected_workflow():
    # Workspace middleware enforces authentication, owner mailbox access and CSRF.
    if current_workspace()!=OWNER:return jsonify(ok=False,error='Sign in to the connected workspace to activate a workflow.'),403
    data=request.get_json(silent=True) or {}
    if data.get('activate') is not True:return jsonify(ok=False,error='Explicit workflow activation is required.'),400
    ref=data.get('selection') or {}
    if not isinstance(ref,dict):return jsonify(ok=False,error='Invalid business selection.'),400
    keys=('kind','lead_id') if ref.get('kind')=='lead' else ('kind','job_id','key')
    ref={key:ref.get(key) for key in keys}
    selected=resolve_selection(ref)
    if not selected:return jsonify(ok=False,error='This business was not found in your research or saved leads.'),404
    offer=str(data.get('offer') or '').strip()[:1200]
    if not offer:return jsonify(ok=False,error='Describe your offer in Task options before activating this workflow.'),400
    row,query,territory,lead_id=selected
    # The same explicit selection and offer always resolve to one job, even if
    # the result's verification snapshot later changes or the browser retries.
    binding=json.dumps([current_workspace(),ref,offer],sort_keys=True)
    request_key='selection:'+hashlib.sha256(binding.encode()).hexdigest()
    base_key=request_key
    retry=data.get('retry_from')
    if retry:
        prior=db.session.get(CampaignExecutionJob,retry) if isinstance(retry,str) else None
        if not prior or not owns('campaign',prior.id) or _unpack(prior.payload_json).get('_selection_base')!=base_key:
            return jsonify(ok=False,error='Workflow not found.'),404
        request_key=base_key+':'+prior.id
    existing=CampaignExecutionJob.query.filter_by(request_key=request_key).first()
    if existing:
        if not owns('campaign',existing.id):return jsonify(ok=False,error='Workflow not found.'),404
        return jsonify(_view(existing)),202
    if retry:
        result=_unpack(prior.result_json);workflow=result.get('workflow') or {}
        if prior.status!='completed' or workflow.get('state')!='held':
            return jsonify(ok=False,error='Review the saved workflow before retrying.'),409
        if workflow.get('lead_id') and oa.OutreachSendAttempt.query.filter_by(lead_id=workflow['lead_id']).first():
            return jsonify(ok=False,error='An earlier send attempt requires review; it cannot be replayed.'),409
        if prior.finished_at and datetime.utcnow()-prior.finished_at<timedelta(seconds=60):
            return jsonify(ok=False,error='Review the held checks, then wait a minute before retrying.'),429
        if CampaignExecutionJob.query.filter(CampaignExecutionJob.request_key.like(base_key+'%'),
                CampaignExecutionJob.created_at>datetime.utcnow()-timedelta(hours=1)).count()>=4:
            return jsonify(ok=False,error='This business has reached its hourly verification retry limit.'),429
    payload={'_selection_base':base_key,'_selected_workflow':True,'_selected_workspace':current_workspace(),
             '_selected_business':row,'_selected_lead_id':lead_id,'_selection_reference':ref,
             'target_customer':query,'query':query,'territory':territory,'offer':offer,
             'target_count':1,'sending_limit':1,'send_authorized':False,'draft_only':True,
             '_selection_send_authorized':True}
    return enqueue_execution('campaign',payload,request_key)



def _email_for_selection(selected):
    row,_,_,lead_id=selected
    if lead_id:
        lead=db.session.get(oa.OutreachLead,lead_id)
        return oa.normalize_email(lead.contact_email) if lead else ''
    values=[row.get('contact_email'),row.get('email')]
    values += [c.get('email') for c in (row.get('contacts') or []) if isinstance(c,dict)]
    return next((oa.normalize_email(x) for x in values if x and '@' in str(x)), '')


@app.post('/api/chat/workflows/activate-bulk')
def activate_bulk_workflow():
    if current_workspace()!=OWNER:return jsonify(ok=False,error='Sign in to the connected workspace to activate outreach.'),403
    data=request.get_json(silent=True) or {}
    refs=data.get('selections')
    if data.get('activate') is not True:return jsonify(ok=False,error='Explicit batch activation is required.'),400
    if not isinstance(refs,list) or not 1<=len(refs)<=20:
        return jsonify(ok=False,error='Choose between 1 and 20 displayed businesses with email per batch.'),400
    offer=str(data.get('offer') or '').strip()[:1200]
    if not offer:return jsonify(ok=False,error='Describe your offer in Task options first.'),400
    items=[];seen=set();missing_email=False
    # Resolve the entire selection before scheduling anything. A forged or
    # foreign reference cannot partially authorize other sends.
    for ref in refs:
        if not isinstance(ref,dict):return jsonify(ok=False,error='Invalid business selection.'),400
        keys=('kind','lead_id') if ref.get('kind')=='lead' else ('kind','job_id','key')
        ref={key:ref.get(key) for key in keys}
        selected=resolve_selection(ref)
        if not selected:return jsonify(ok=False,error='A selected business was not found in your results.'),404
        email=_email_for_selection(selected)
        if not email:missing_email=True
        canonical=json.dumps(ref,sort_keys=True)
        if canonical in seen:continue
        seen.add(canonical)
        row,query,territory,lead_id=selected
        items.append({'selection':ref,'company':row.get('company') or row.get('title') or row.get('name') or '',
                      'payload':{'_selected_workflow':True,'_selected_workspace':OWNER,'_selection_send_authorized':True,
                                 '_selected_business':row,'_selected_lead_id':lead_id,'_selection_reference':ref,
                                 'query':query,'target_customer':query,'territory':territory,'offer':offer,
                                 'target_count':1,'sending_limit':1,'draft_only':True,'send_authorized':False}})
    binding=json.dumps([OWNER,sorted(seen),offer],sort_keys=True)
    key='selection-bulk:'+hashlib.sha256(binding.encode()).hexdigest()
    existing=CampaignExecutionJob.query.filter_by(request_key=key).first()
    if existing:
        if not owns('campaign',existing.id):return jsonify(ok=False,error='Batch not found.'),404
        return jsonify(_view(existing)),202
    if missing_email:return jsonify(ok=False,error='A selected business has no saved email. Refresh your results before activation.'),409
    return enqueue_execution('campaign',{'_selected_bulk':True,'_selected_workspace':OWNER,
        '_selection_send_authorized':True,'items':items,'offer':offer,'target_customer':'Selected businesses with email',
        'target_count':len(items),'sending_limit':len(items),'draft_only':True,'send_authorized':False},key)


def run_bulk_selected_workflows(data,job_id):
    from src.execution_deadline import checkpoint,hard_stage_limit
    items=data.get('items') or []
    if (data.get('_selected_workspace')!=OWNER or data.get('_selection_send_authorized') is not True
            or not owns('campaign',job_id,OWNER) or not 1<=len(items)<=20):
        return None,'authorization','BULK_WORKFLOW_AUTHORIZATION_REQUIRED'
    results=[{'selection':x['selection'],'company':x['company'],'status':'queued',
              'workflow':{'lead_id':x['payload'].get('_selected_lead_id'),'state':'pending'}} for x in items]
    for index,item in enumerate(items):
        results[index]['status']='running'
        checkpoint('activating_email_batch',bulk_items=results,batch_requested=len(items),batch_completed=index)
        try:
            with hard_stage_limit(185,'bulk_business'):
                outcome,stage,reason=run_selected_workflow(item['payload'],job_id)
            results[index].update(status='completed' if outcome else 'failed',
                workflow=(outcome or {}).get('workflow') or {'state':'held','reason':reason or 'This business requires review.',
                                                          'outreach':{'send_status':'unknown','state':'review'}},
                outreach=(outcome or {}).get('outreach') or {})
        except TimeoutError as exc:
            # Claim loss, cancellation and the overall deadline always fence the
            # batch. A per-business deadline may leave an external effect unknown.
            if str(exc)!='BULK_BUSINESS_DEADLINE_EXCEEDED':raise
            db.session.rollback()
            results[index].update(status='failed',workflow={'state':'held','reason':'This business timed out. Review its send status before retrying.',
                                                           'outreach':{'send_status':'unknown','state':'review'}})
        except Exception:
            db.session.rollback()
            results[index].update(status='failed',workflow={'state':'held','reason':'This business could not finish. Review its saved send status.',
                                                           'outreach':{'send_status':'unknown','state':'review'}})
        checkpoint('activating_email_batch',bulk_items=results,batch_requested=len(items),batch_completed=index+1)
    sent=sum((x.get('workflow',{}).get('outreach') or {}).get('send_status')=='sent' for x in results)
    return {'ok':True,'bulk_items':results,'batch':{'requested':len(items),'sent':sent,'not_sent_or_review':len(items)-sent},
            'outreach':{'sent':sum((x.get('outreach') or {}).get('sent',0) for x in results)},
            'campaign':{'target_customer':'Selected businesses with email','offer':data.get('offer'),'target_count':len(items)}},None,None

def run_selected_workflow(data,job_id):
    from src.execution_deadline import checkpoint
    from src.prospect_quality import POLICY,request_spec
    from v1_orchestration import _orchestrate_discovery_serial,discovery_lock
    from src.outreach_activation import activate_prepared_contact,activation_view
    if data.get('_selected_workspace')!=OWNER or data.get('_selection_send_authorized') is not True:
        return None,'authorization','SELECTED_WORKFLOW_AUTHORIZATION_REQUIRED'
    job=db.session.get(CampaignExecutionJob,job_id)
    if not job or not owns('campaign',job_id,OWNER):return None,'authorization','WORKFLOW_OWNERSHIP_REQUIRED'
    checkpoint('checking_selection_grant')
    selected=data.get('_selected_business') or {}
    company=str(selected.get('company') or selected.get('name') or selected.get('business_name') or selected.get('candidate_name') or selected.get('title') or '')[:300]
    website=selected.get('website') or selected.get('source_url') or selected.get('url') or ''
    # Reuse the owned company's canonical record across source URL paths and
    # successive searches; never create a new mailbox identity to retry a send.
    matching=[lead for lead in oa.OutreachLead.query.filter(scope(oa.OutreachLead,'lead',OWNER)).all()
              if name_key(lead.company)==name_key(company) and owned_host(lead.source_url,website)]
    if len(matching)>1:
        return {'ok':True,'workflow':{'state':'held','reason':'Duplicate saved records require review before outreach.'}},None,None
    existing=matching[0] if matching else None
    expected=data.get('_selected_lead_id')
    if expected and (not existing or existing.id!=expected):return None,'ownership','SELECTED_LEAD_MISMATCH'
    if existing:company=existing.company;website=existing.source_url
    selected={**selected,'company':company,'website':website,'source_url':website}
    checkpoint('verifying_selected_business',requested=1,businesses=[{
        'company':company,'source_url':website,'business_status':'Checking selected business',
        'contact_status':'Contact pending','draft_status':'No draft ready','status':'running'}])
    payload={'query':data['query'],'goal':data['query'],'location':data['territory'],'offer':data['offer'],
             'results':[selected],'prospect_policy':POLICY,
             'request_spec':request_spec(data['query'],data['territory'],data['offer']),
             '_selected_workflow':True,'_selected_workspace':OWNER}
    # Selection may begin before a draft exists. This stage has no send authority.
    summary=_orchestrate_discovery_serial(payload,draft_only=True)
    ids=list(dict.fromkeys(summary.get('lead_ids') or []))
    lead=db.session.get(oa.OutreachLead,ids[0]) if len(ids)==1 else None
    workflow={'state':'held','reason':'Business or contact verification needs more evidence. No email was sent.'}
    if lead:
        if not owns('lead',lead.id,OWNER):return None,'ownership','SELECTED_LEAD_OWNERSHIP_REQUIRED'
        checkpoint('checking_selected_send_authorization')
        # report_stage refreshes/fences the exact current job claim before send.
        # Serialize the actual recipient across different source/lead identities.
        with discovery_lock('selected-recipient',oa.normalize_email(lead.contact_email) or str(lead.id)) as acquired:
            if not acquired:
                outcome={'ok':False,'error':'Another selected workflow is checking this recipient. Review its status before retrying.',
                         'reason_codes':['RECIPIENT_WORKFLOW_IN_PROGRESS']}
            else:
                duplicate=oa.OutreachSendAttempt.query.join(oa.OutreachLead,oa.OutreachLead.id==oa.OutreachSendAttempt.lead_id).filter(
                    scope(oa.OutreachLead,'lead',OWNER),oa.OutreachSendAttempt.lead_id!=lead.id,
                    oa.OutreachSendAttempt.recipient==oa.normalize_email(lead.contact_email),
                    oa.OutreachSendAttempt.kind=='initial').first() if lead.contact_email else None
                if duplicate:
                    outcome={'ok':False,'error':'This recipient already has an initial send or attempt on another saved lead. Review it before sending again.',
                             'reason_codes':['DUPLICATE_RECIPIENT_SEND_REVIEW_REQUIRED']}
                else:
                    response=app.make_response(activate_prepared_contact(lead));outcome=response.get_json() or {}
        state=activation_view(lead)
        workflow={'state':'active' if outcome.get('ok') and state.get('state')=='active' else 'held',
                  'reason':state.get('reason') if outcome.get('ok') else outcome.get('error') or state.get('reason'),
                  'lead_id':lead.id,'outreach':state,'reason_codes':outcome.get('reason_codes') or state.get('reason_codes') or []}
        if not outcome.get('ok'):
            receipt=oa._qualification_gate(lead)
            workflow['reason_codes']=list(dict.fromkeys(workflow['reason_codes']+(receipt.get('reason_codes') or [])))
        summary['sent']=int(workflow['state']=='active' and not outcome.get('already_active'))
        oa._audit_actor(lead.id,'selected_workflow_finished',{'job_id':job_id,'explicit':True},
                        {'state':workflow['state'],'reason_codes':workflow['reason_codes']},'customer')
        db.session.commit()
    return {'ok':True,'workflow':workflow,'outreach':summary,'discovery':{'results':[selected]},
            'campaign':{'target_customer':data['query'],'territory':data['territory'],'offer':data['offer'],'target_count':1}},None,None
