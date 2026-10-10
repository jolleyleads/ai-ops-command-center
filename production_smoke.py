"""Explicit, one-shot live checks on the existing scheduled worker.

Disabled unless an operator supplies a run ID and real Gmail thread/message
receipts. Never selects a prospect or reuses the booked conversation.
"""
import json
import os
import hashlib
from datetime import datetime, timedelta
from app import app, db


class ProductionSmokeRun(db.Model):
    __tablename__="production_smoke_run"
    id=db.Column(db.String(48),primary_key=True)
    research_job_id=db.Column(db.String(48))
    test_lead_id=db.Column(db.Integer)
    prepared=db.Column(db.Boolean,default=False)
    followup_result_json=db.Column(db.Text,default="")
    completed=db.Column(db.Boolean,default=False)


with app.app_context():db.create_all()


def run_configured_smoke():
    run_id=os.getenv("AUTOMAKE_SMOKE_RUN_ID","").strip()[:48]
    if not run_id:return {"enabled":False}
    from background_research import ResearchJob
    import outreach_automation as oa
    row=db.session.get(ProductionSmokeRun,run_id)
    if row and row.completed:return {"enabled":True,"completed":True}
    if row is None:
        row=ProductionSmokeRun(id=run_id)
        db.session.add(row);db.session.commit()
    if not row.prepared:
        from operator_conversation_import import import_and_process
        result=import_and_process({"recipient":"neyolabs@gmail.com","company":"AutoMake controlled follow-up test","thread_id":os.getenv("AUTOMAKE_SMOKE_THREAD_ID",""),"message_id":os.getenv("AUTOMAKE_SMOKE_MESSAGE_ID","")})
        if not result.get("ok"):
            app.logger.warning("PRODUCTION_SMOKE_SETUP_FAILED %s",json.dumps(result))
            return {"enabled":True,"ok":False,"stage":"setup"}
        lead=db.session.get(oa.OutreachLead,result.get("lead_id"))
        if result.get("stage")!="awaiting_real_reply" or not lead or lead.replied_at or lead.follow_up_count:
            return {"enabled":True,"ok":False,"stage":"TEST_THREAD_MUST_BE_UNANSWERED"}
        lead.verification="controlled_followup_test"
        lead.follow_up_due_at=datetime.utcnow()+timedelta(minutes=1)
        row.test_lead_id=lead.id
        row.research_job_id="smoke-"+hashlib.sha256(run_id.encode()).hexdigest()[:32]
        if not db.session.get(ResearchJob,row.research_job_id):
            db.session.add(ResearchJob(id=row.research_job_id,prompt_text="Find 3 businesses in Hampton Roads Virginia hiring automation engineers or with dated reviews about unanswered calls. Include direct supporting sources and distinguish confirmed evidence from candidates.",location="Hampton Roads Virginia",target_count=3,status="queued"))
        row.prepared=True;db.session.commit()
    lead=db.session.get(oa.OutreachLead,row.test_lead_id)
    if not row.followup_result_json and lead.follow_up_due_at and lead.follow_up_due_at<=datetime.utcnow():
        result=oa.process_due_followups(controlled_test_lead_id=lead.id)
        row.followup_result_json=json.dumps(result)
        # Exactly one controlled follow-up; never leave later reminders queued.
        lead.follow_up_due_at=None
        db.session.commit()
        app.logger.warning("PRODUCTION_SMOKE_FOLLOWUP %s",json.dumps(result))
    job=db.session.get(ResearchJob,row.research_job_id)
    if job.status in {"completed","failed"}:
        data=json.loads(job.result_json or "{}")
        summary={"status":job.status,"verified_count":data.get("verified_count"),"target_met":data.get("target_met"),"results":[{k:x.get(k) for k in ("title","url","promotion_status","verified_claim","published_at","freshness_note")} for x in data.get("results",[])],"error":job.error}
        app.logger.warning("PRODUCTION_SMOKE_SEARCH %s",json.dumps(summary))
        if row.followup_result_json:
            row.completed=True;db.session.commit()
    return {"enabled":True,"prepared":row.prepared,"completed":row.completed,"research_job_id":row.research_job_id,"test_lead_id":row.test_lead_id}
