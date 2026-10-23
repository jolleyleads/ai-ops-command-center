"""Durable per-business draft work, isolated from other contacts and send authority."""
import hashlib
import json
import multiprocessing
import os
import time
from datetime import datetime
from app import app, db


class CampaignBusinessTask(db.Model):
    __tablename__='campaign_business_task'
    id=db.Column(db.String(64),primary_key=True)
    campaign_id=db.Column(db.String(48),nullable=False,index=True)
    business_json=db.Column(db.Text,nullable=False)
    status=db.Column(db.String(24),nullable=False,default='queued')
    stage=db.Column(db.String(80),default='contact_pending')
    result_json=db.Column(db.Text,default='{}')
    error=db.Column(db.String(160),default='')
    started_at=db.Column(db.DateTime)
    updated_at=db.Column(db.DateTime,default=datetime.utcnow)
    finished_at=db.Column(db.DateTime)

with app.app_context():db.create_all()


def task_views(campaign_id):
    rows=CampaignBusinessTask.query.filter_by(campaign_id=campaign_id).order_by(CampaignBusinessTask.id).all()
    from campaign_jobs import CampaignExecutionJob
    parent=db.session.get(CampaignExecutionJob,campaign_id)
    views=[]
    for row in rows:
        business=json.loads(row.business_json);result=json.loads(row.result_json or '{}')
        status=row.status;error=row.error
        if status in {'queued','running'} and parent and parent.status not in {'queued','running'}:
            status='interrupted';error='CAMPAIGN_INTERRUPTED_REVIEW_REQUIRED'
        lead_ids=result.get('lead_ids') or []
        lead_id=lead_ids[0] if len(lead_ids)==1 and type(lead_ids[0]) is int else None
        from outreach_automation import OutreachLead
        from src.outreach_activation import activation_view
        lead=db.session.get(OutreachLead,lead_id) if lead_id else None
        from src.prospect_quality import for_lead
        quality=for_lead(lead) if lead else business.get('prospect_quality')
        contact_check=next(iter(result.get('contact_checks') or []),None)
        contact_status=(('Decision-maker email verified' if contact_check['named_contact'] else 'Company email verified')
                        if contact_check and contact_check['mailbox_verified'] else
                        'Contact not verified' if contact_check else
                        ('Contact '+quality['contact']['state'].lower()) if quality else
                        ('Verified contact' if result.get('qualified') else ('Contact not started — business not verified' if business.get('classification')!='Verified Lead' else ('Contact pending' if status in {'queued','running'} else 'Contact requires review'))))
        from workspace_security import owns
        email=lead.contact_email if lead and owns('lead',lead.id) else ''
        views.append({'contact_email':email,'lead_id':lead_id,'outreach':activation_view(lead) if lead else None,'task_id':row.id,'company':business.get('company') or business.get('title') or business.get('name'),
            'prospect_quality':quality,
            'source_url':business.get('website') or business.get('source_url') or business.get('url'),
            'business_status':{'Verified Lead':'Business verified','Rejected':'Business rejected','Needs More Evidence':'Business held — more evidence required'}.get(business.get('classification'),'Candidate — verification pending'),
            'contact_status':contact_status,'contact_check':contact_check,
            'qualification_status':'Qualified' if result.get('qualified') else 'Not qualified',
            'draft_status':'Draft ready' if result.get('drafted') else 'No draft ready',
            'status':status,'stage':row.stage,'error':error,'updated_at':row.updated_at.isoformat()+'Z'})
    return views


def _execute_task(task_id,payload):
    # Forked children must not share the parent's DB sockets or Session.
    db.session.remove();db.engine.dispose(close=False)
    from v1_orchestration import _orchestrate_discovery_serial
    from src.execution_deadline import execution_scope
    from src.campaign_reporting import reporting_campaign
    task=db.session.get(CampaignBusinessTask,task_id)
    if not task or task.status!='running':return
    campaign_id=task.campaign_id
    def stage(details):
        from campaign_jobs import CampaignExecutionJob
        db.session.expire_all()
        parent=db.session.get(CampaignExecutionJob,campaign_id)
        if not parent or parent.status!='running':raise TimeoutError('CAMPAIGN_STOPPED')
        updates={'stage':details['stage'],'updated_at':datetime.utcnow()}
        if details.get('prospect_quality'):
            business=json.loads(task.business_json)
            business['prospect_quality']=details['prospect_quality']
            updates['business_json']=json.dumps(business)
        changed=CampaignBusinessTask.query.filter_by(id=task_id,status='running').update(updates,synchronize_session=False)
        db.session.commit()
        if not changed:raise TimeoutError('CONTACT_CLAIM_LOST')
    try:
        with execution_scope(185,stage),reporting_campaign(campaign_id):
            result=_orchestrate_discovery_serial(payload,draft_only=True)
        status='completed' if result.get('drafted') else 'held'
        error='' if status=='completed' else 'CONTACT_OR_QUALIFICATION_REQUIRES_REVIEW'
        CampaignBusinessTask.query.filter_by(id=task_id,status='running').update({
            'status':status,'stage':'draft_ready' if result.get('drafted') else 'held',
            'result_json':json.dumps(result),'error':error,'updated_at':datetime.utcnow(),'finished_at':datetime.utcnow()},synchronize_session=False)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        CampaignBusinessTask.query.filter_by(id=task_id,status='running').update({
            'status':'failed','error':'CONTACT_ENRICHMENT_DEADLINE_EXCEEDED' if isinstance(exc,TimeoutError) else 'CONTACT_TASK_FAILED',
            'updated_at':datetime.utcnow(),'finished_at':datetime.utcnow()},synchronize_session=False)
        db.session.commit()
    finally:db.session.remove()


def run_business_tasks(payload,campaign_id,send_enabled,limit):
    from campaign_jobs import CampaignExecutionJob
    from src.execution_deadline import checkpoint
    from v1_orchestration import _send_prepared_lead
    from outreach_automation import OutreachLead
    from src.company_identity import name_key
    summary={'enabled':True,'autosend_enabled':send_enabled,'lead_ids':[],'eligible':0,'saved':0,'qualified':0,'drafted':0,'sent':0,'skipped':[],'contact_checks':[]}
    tasks=[];seen=set()
    for business in payload.get('results') or []:
        if not isinstance(business,dict):continue
        identity=name_key(business.get('company') or business.get('title') or business.get('name') or '')
        if not identity or identity in seen:continue
        seen.add(identity)
        key=hashlib.sha256((campaign_id+'|'+identity).encode()).hexdigest()
        task=db.session.get(CampaignBusinessTask,key)
        if not task:
            task=CampaignBusinessTask(id=key,campaign_id=campaign_id,business_json=json.dumps(business))
            db.session.add(task)
        tasks.append(key)
    db.session.commit()
    # Explicitly two child processes: a blocked socket or parser cannot hold the
    # other business's interpreter. No child has permission to send.
    context=multiprocessing.get_context('fork')
    active={};finished=set();counted=set();fingerprint=None
    def fail_task(key,reason):
        CampaignBusinessTask.query.filter_by(id=key,status='running').update({
            'status':'failed','error':reason,'updated_at':datetime.utcnow(),'finished_at':datetime.utcnow()},synchronize_session=False)
        db.session.commit()
    try:
        while len(finished)<len(tasks):
            db.session.expire_all()
            job=db.session.get(CampaignExecutionJob,campaign_id)
            if not job or job.status!='running':break
            if send_enabled and limit and summary['sent']>=limit:break
            for key in tasks:
                if key in finished or key in active:continue
                task=db.session.get(CampaignBusinessTask,key)
                if task.status!='queued':finished.add(key);continue
                if len(active)>=2:break
                task.status='running';task.started_at=datetime.utcnow();task.updated_at=task.started_at;db.session.commit()
                single={**payload,'results':[json.loads(task.business_json)]}
                db.session.remove()
                process=context.Process(target=_execute_task,args=(key,single),daemon=False)
                process.start();active[key]=(process,time.monotonic())
            for key,(process,started) in list(active.items()):
                if process.is_alive() and time.monotonic()-started<190:continue
                if process.is_alive():process.terminate();process.join(3)
                if process.is_alive():process.kill()
                process.join(3)
                db.session.expire_all();fail_task(key,'CONTACT_PROCESS_INTERRUPTED_REVIEW_REQUIRED')
                del active[key];finished.add(key)
            for key in finished-counted:
                task=db.session.get(CampaignBusinessTask,key)
                result=json.loads(task.result_json or '{}');counted.add(key)
                for metric in ('eligible','saved','qualified','drafted'):summary[metric]+=result.get(metric,0)
                summary['lead_ids']+=result.get('lead_ids') or []
                summary['contact_checks']+=result.get('contact_checks') or []
                summary['skipped']+=result.get('skipped') or []
                if task.error:summary['skipped'].append({'task_id':key,'reason':task.error})
                if send_enabled:
                    for lead_id in result.get('lead_ids') or []:
                        if limit and summary['sent']>=limit:break
                        checkpoint('checking_send_authorization')
                        db.session.expire_all();job=db.session.get(CampaignExecutionJob,campaign_id)
                        if not job or job.status!='running':break
                        lead=db.session.get(OutreachLead,lead_id)
                        # Only this new draft may advance. Reused or uncertain work is never replayed.
                        if not lead or not result.get('drafted') or lead.status!='drafted':continue
                        if _send_prepared_lead(lead,summary):summary['sent']+=1
            views=task_views(campaign_id)
            signature=json.dumps(views,sort_keys=True)
            if signature!=fingerprint:
                checkpoint('enriching_individual_contacts',businesses=views,qualified=summary['qualified'],drafted=summary['drafted'],sent=summary['sent'])
                fingerprint=signature
            if len(finished)<len(tasks):time.sleep(0.2)
    finally:
        for key,(process,_) in active.items():
            if process.is_alive():process.terminate();process.join(3)
            if process.is_alive():process.kill();process.join(3)
            fail_task(key,'CONTACT_PROCESS_INTERRUPTED_REVIEW_REQUIRED')
        CampaignBusinessTask.query.filter(CampaignBusinessTask.campaign_id==campaign_id,CampaignBusinessTask.status=='queued').update({
            'status':'cancelled','error':'CAMPAIGN_STOPPED_BEFORE_CONTACT_STARTED','updated_at':datetime.utcnow(),'finished_at':datetime.utcnow()},synchronize_session=False)
        db.session.commit()
    summary['lead_ids']=list(dict.fromkeys(summary['lead_ids']))
    return summary
