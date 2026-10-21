"""Real fork/process isolation on a disposable DB, without provider or send calls."""
import json
import os
import subprocess
import sys
from pathlib import Path


def test_fast_contact_completes_while_slow_contact_runs_and_cancellation_fences_it(tmp_path):
    script=r'''
import time,json
import commercial_app
from app import app,db
from campaign_jobs import CampaignExecutionJob
from src.progressive_campaign import CampaignBusinessTask,run_business_tasks,task_views
from src.execution_deadline import execution_scope
import v1_orchestration as v

def fake(payload,**kw):
    assert kw=={'draft_only':True}
    row=payload['results'][0]
    time.sleep(3 if row['title']=='Slow Business' else 0.05)
    return {'eligible':1,'saved':0,'qualified':1,'drafted':1,'sent':0,'lead_ids':[],'skipped':[]}
v._orchestrate_discovery_serial=fake
v._send_prepared_lead=lambda *a:(_ for _ in ()).throw(AssertionError('No sends allowed'))
with app.app_context():
    job=CampaignExecutionJob(id='isolated',kind='campaign',payload_json='{}',status='running')
    db.session.add(job);db.session.commit()
    seen=[]
    def progress(p):
        views=p.get('businesses') or []
        fast=next((r for r in views if r['company']=='Fast Business'),None)
        slow=next((r for r in views if r['company']=='Slow Business'),None)
        if fast and fast['draft_status']=='Draft ready' and slow and slow['status']=='running':
            seen.append(True)
            job=db.session.get(CampaignExecutionJob,'isolated');job.status='cancelled'
            CampaignBusinessTask.query.filter_by(campaign_id='isolated',status='running').update({'status':'cancelled'})
            db.session.commit()
    rows=[{'title':name,'website':'https://'+name.split()[0].lower()+'.example/','classification':'Verified Lead'} for name in ['Slow Business','Fast Business','Fast Business']]
    started=time.monotonic()
    with execution_scope(10,progress):summary=run_business_tasks({'results':rows},'isolated',False,1)
    assert seen and time.monotonic()-started<2
    assert CampaignBusinessTask.query.count()==2
    views=task_views('isolated')
    assert next(r for r in views if r['company']=='Fast Business')['draft_status']=='Draft ready'
    assert next(r for r in views if r['company']=='Slow Business')['status']=='cancelled'
    assert summary['sent']==0 and summary['drafted']==1
    import campaign_jobs as jobs,customer_demo as demo
    def run(payload):
        return {'ok':True,'outreach':v.orchestrate_discovery({'query':'businesses','results':[{'title':'Fresh Business','website':'https://fresh.example','classification':'Verified Lead'}]},draft_only=True)},None,None
    demo._run_campaign=run
    job=CampaignExecutionJob(id='integrated',kind='campaign',payload_json='{}',status='queued')
    db.session.add(job);db.session.commit()
    assert jobs.process_next_execution_job()['ok']
    final=jobs._view(db.session.get(CampaignExecutionJob,'integrated'))
    assert final['status']=='completed' and final['result']['outreach']['drafted']==1
    assert final['progress']['businesses'][0]['draft_status']=='Draft ready'
print('isolated-process-progress-and-cancellation: PASS')
'''
    env={**os.environ,'DATABASE_URL':'sqlite:///'+str(tmp_path/'fork.db'),'AUTOMAKE_ISOLATED_EXECUTION':'1','OUTREACH_INPROCESS_SCHEDULER':'0'}
    result=subprocess.run([sys.executable,'-c',script],env=env,capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr[-6000:]
    assert 'PASS' in result.stdout


def test_first_provider_publishes_before_second_finishes(monkeypatch):
    import smart_search as engine
    from src.execution_deadline import execution_scope
    import threading,time
    held=threading.Event();seen=[]
    def tool(call):
        if call['tool']=='slow':held.wait(1)
        return ([{'title':'Real source name','url':'https://business.example/','research_tool':'business_search'}],'')
    monkeypatch.setattr(engine,'_run_tool',tool)
    def progress(details):
        seen.append(details)
        if len(seen)==1:
            assert not held.is_set()
            held.set()
    with execution_scope(2,progress):engine._run_calls([{'tool':'fast'},{'tool':'slow'}],time.monotonic()+2)
    assert seen[0]['candidates'][0]['classification']=='Candidate'
    assert seen[0]['candidates'][0]['source_url']=='https://business.example/'


def test_one_provider_failure_keeps_other_source_results(monkeypatch):
    import smart_search as engine
    import time
    def tool(call):
        if call['tool']=='failed':raise RuntimeError('provider failure')
        return ([{'title':'Source name','url':'https://business.example','research_tool':'business_search'}],'')
    monkeypatch.setattr(engine,'_run_tool',tool)
    rows,messages,used=engine._run_calls([{'tool':'failed'},{'tool':'working'}],time.monotonic()+1)
    assert len(rows)==1 and used==['working']
    assert any('provider failed' in message for message in messages)
