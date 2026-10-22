"""Persisted campaign execution with atomic claims; interrupted sends are never replayed."""
import json
import secrets
import threading
import os
import subprocess
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from flask import jsonify
from app import app, db


class CampaignExecutionJob(db.Model):
    __tablename__ = "campaign_execution_job"
    id = db.Column(db.String(48), primary_key=True)
    request_key = db.Column(db.String(200), unique=True, nullable=True)
    kind = db.Column(db.String(20), nullable=False)
    payload_json = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), nullable=False, default="queued", index=True)
    result_json = db.Column(db.Text, default="{}")
    result_http_status = db.Column(db.Integer)
    error = db.Column(db.String(200), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    started_at = db.Column(db.DateTime)
    finished_at = db.Column(db.DateTime)


with app.app_context():
    db.create_all()
_pool = None
_lock = threading.Lock()
_future = None
_pool_pid = None


def reset_worker_pool():
    """A preloaded Gunicorn fork must not inherit a dead executor or held lock."""
    global _pool, _lock, _future, _pool_pid
    _pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="campaign-execution")
    _lock = threading.Lock()
    _future = None
    _pool_pid = os.getpid()


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=reset_worker_pool)


def execution_limit(kind):
    return 2400 if kind == "acceptance" else 1200


def expire_interrupted_jobs():
    """Polling also expires dead workers; no send-capable claim is replayed."""
    now = datetime.utcnow()
    CampaignExecutionJob.query.filter(CampaignExecutionJob.status=="queued",
        CampaignExecutionJob.created_at<now-timedelta(minutes=30)).update({
        "status":"failed","error":"QUEUE_DEADLINE_EXCEEDED_NO_EXECUTION",
        "result_http_status":503,"result_json":json.dumps({"ok":False,"reason":"QUEUE_DEADLINE_EXCEEDED_NO_EXECUTION"}),"finished_at":now})
    for kind in ("campaign", "acceptance"):
        expired=CampaignExecutionJob.query.filter(
            CampaignExecutionJob.kind==kind, CampaignExecutionJob.status=="running",
            CampaignExecutionJob.started_at<now-timedelta(seconds=execution_limit(kind))).all()
        for job in expired:
            reason="EXECUTION_INTERRUPTED_REVIEW_REQUIRED"
            CampaignExecutionJob.query.filter_by(id=job.id,status="running",started_at=job.started_at).update({
                "status":"failed","error":reason,"result_http_status":504,
                "result_json":failure_result(job,reason),"finished_at":now},synchronize_session=False)
    db.session.commit()


def failure_result(job,reason):
    try:progress=json.loads(job.result_json or "{}").get("progress") or {}
    except (TypeError,ValueError):progress={}
    return json.dumps({"ok":False,"reason":reason,"progress":progress})


def execute_claimed_job(job_id):
    job = db.session.get(CampaignExecutionJob, job_id)
    if not job or job.status != "running":
        return {"processed":0}
    claim_started_at=job.started_at
    try:
        import customer_demo as demo
        from src.execution_deadline import execution_scope
        from src.campaign_reporting import reporting_campaign
        def report_stage(progress):
            now=datetime.utcnow()
            previous=json.loads(db.session.get(CampaignExecutionJob,job_id).result_json or "{}").get("progress") or {}
            progress={**previous,**progress}
            changed=CampaignExecutionJob.query.filter_by(id=job_id,status="running",started_at=claim_started_at).update(
                {"result_json":json.dumps({"progress":{**progress,"updated_at":now.isoformat()+"Z"}})},synchronize_session=False)
            db.session.commit()
            if changed and (progress.get('stage')!=previous.get('stage') or progress.get('campaign_index')!=previous.get('campaign_index')):
                app.logger.warning('CAMPAIGN_PROGRESS job_id=%s stage=%s campaign_index=%s discovered=%s',
                                   job_id,progress.get('stage'),progress.get('campaign_index'),progress.get('discovered'))
            if not changed:
                raise TimeoutError("EXECUTION_CLAIM_LOST_REVIEW_REQUIRED")
        if job.kind == "acceptance":
            campaign=json.loads(job.payload_json).get('campaign')
            with execution_scope(execution_limit(job.kind)-5, report_stage), reporting_campaign(job_id):
                response = app.make_response(demo._run_acceptance(campaign, progress_callback=report_stage))
            result, code = response.get_json(), response.status_code
        else:
            with execution_scope(execution_limit(job.kind)-5, report_stage), reporting_campaign(job_id):
                payload=json.loads(job.payload_json)
                if payload.get('_selected_bulk'):
                    from src.selection_workflows import run_bulk_selected_workflows
                    result,stage,reason=run_bulk_selected_workflows(payload,job_id)
                elif payload.get('_selected_workflow'):
                    from src.selection_workflows import run_selected_workflow
                    result,stage,reason=run_selected_workflow(payload,job_id)
                else:
                    result, stage, reason = demo._run_campaign(payload)
            code = 200 if result else 500
            result = result or {"ok":False, "stage":stage, "reason":reason}
        job=db.session.get(CampaignExecutionJob,job_id)
        db.session.refresh(job)
        if job.status != "running":
            return {"processed":1,"job_id":job_id,"ok":False}
        job.result_json = json.dumps(result)
        job.result_http_status = code
        job.status = "completed" if code == 200 and result.get("ok") is True else "failed"
        job.error = "" if job.status == "completed" else str(result.get("reason") or "EXECUTION_FAILED")[:200]
        discovery=result.get('discovery') or {}
        outreach=result.get('outreach') or {}
        app.logger.warning('CAMPAIGN_EXECUTION_RECEIPT job_id=%s kind=%s status=%s qualified=%s drafted=%s sent=%s', job_id, job.kind, job.status, outreach.get('qualified',0), outreach.get('drafted',0), outreach.get('sent',0))
    except Exception:
        app.logger.exception("CAMPAIGN_EXECUTION_FAILED")
        db.session.rollback()
        job = db.session.get(CampaignExecutionJob, job_id)
        if not job or job.status != "running":
            return {"processed":1,"job_id":job_id,"ok":False}
        job.status = "failed"
        job.error = "EXECUTION_FAILED_REVIEW_REQUIRED"
        job.result_http_status = 500
        job.result_json = failure_result(job,job.error)
    job.finished_at = datetime.utcnow()
    db.session.commit()
    return {"processed":1, "job_id":job_id, "ok":job.status == "completed"}


def process_next_execution_job(*, isolated=False):
    expire_interrupted_jobs()
    job = CampaignExecutionJob.query.filter_by(status="queued").order_by(CampaignExecutionJob.created_at).first()
    if not job:
        return {"processed":0}
    job_id, now = job.id, datetime.utcnow()
    progress={"stage":"starting", "updated_at":now.isoformat()+"Z",
              "deadline_at":(now+timedelta(seconds=execution_limit(job.kind))).isoformat()+"Z"}
    claimed = CampaignExecutionJob.query.filter_by(id=job_id,status="queued").update(
        {"status":"running","started_at":now,"result_json":json.dumps({"progress":progress})})
    db.session.commit()
    if not claimed:
        return {"processed":0}
    if not isolated:
        return execute_claimed_job(job_id)
    # A separate process gives provider/DNS stalls a hard wall-clock boundary.
    # Terminating an uncertain external effect requires review, never a replay.
    kind=job.kind
    app.logger.warning("CAMPAIGN_WORKER_CLAIM job_id=%s kind=%s",job_id,kind)
    db.session.remove()
    process=subprocess.Popen([sys.executable,"-m","scripts.execute_campaign_job",job_id],
                             cwd=str(Path(__file__).resolve().parent))
    reason=""
    try:
        code=process.wait(timeout=execution_limit(kind))
        if code:
            reason="EXECUTION_PROCESS_EXITED_REVIEW_REQUIRED"
    except subprocess.TimeoutExpired:
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill();process.wait(timeout=5)
        reason="EXECUTION_DEADLINE_EXCEEDED_REVIEW_REQUIRED"
    finally:
        db.session.remove()
    job=db.session.get(CampaignExecutionJob,job_id)
    if job and job.status=="running":
        reason=reason or "EXECUTION_NO_TERMINAL_RECEIPT_REVIEW_REQUIRED"
        job.status="failed";job.error=reason;job.result_http_status=504
        job.result_json=failure_result(job,reason)
        job.finished_at=datetime.utcnow();db.session.commit()
    return {"processed":1,"job_id":job_id,"ok":bool(job and job.status=="completed")}


def _worker():
    with app.app_context():
        try:
            while process_next_execution_job(isolated=True).get("processed"):
                pass
        except Exception as exc:
            db.session.rollback()
            app.logger.error("CAMPAIGN_WORKER_FAILURE type=%s",type(exc).__name__)
        finally:
            db.session.remove()


def kick_execution_worker():
    global _future
    if _pool_pid != os.getpid():
        reset_worker_pool()
    with _lock:
        if _future is None or _future.done():
            _future = _pool.submit(_worker)


def _view(job):
    result = {"job_id":job.id, "status":job.status, "poll_url":"/api/demo/campaigns/jobs/"+job.id, "error":job.error}
    result["progress"] = json.loads(job.result_json or "{}").get("progress") or {}
    from src.progressive_campaign import task_views
    businesses=task_views(job.id)
    if businesses:result["progress"]={**result["progress"],"businesses":businesses}
    if job.status=="queued":
        result["queue_position"]=CampaignExecutionJob.query.filter(CampaignExecutionJob.status=="queued",CampaignExecutionJob.created_at<=job.created_at).count()
        result["active_executions"]=CampaignExecutionJob.query.filter_by(status="running").count()
    if job.status in {"completed", "failed", "cancelled"}:
        result.update(result=json.loads(job.result_json or "{}"), result_http_status=job.result_http_status)
    from src.selection_refs import annotate
    return annotate(result,'campaign',job.id)


def enqueue_execution(kind, payload, request_key=None):
    from sqlalchemy.exc import IntegrityError
    serialized = json.dumps(payload, sort_keys=True)
    key = str(request_key or "").strip() or None
    if key and len(key) > 200:
        return jsonify({"error":"Idempotency key is too long."}),400
    existing = CampaignExecutionJob.query.filter_by(request_key=key).first() if key else None
    if existing:
        if existing.kind != kind or existing.payload_json != serialized:
            return jsonify({"error":"Idempotency key belongs to a different request."}),409
        kick_execution_worker()
        return jsonify(_view(existing)),202
    if CampaignExecutionJob.query.filter(CampaignExecutionJob.status.in_(["queued", "running"])).count() >= 5:
        return jsonify({"error":"Several campaigns are already running. Please try shortly."}),429
    job = CampaignExecutionJob(id=secrets.token_urlsafe(24), kind=kind, payload_json=serialized, request_key=key)
    from workspace_security import claim, current_workspace, OWNER
    db.session.add(job)
    claim("campaign",job.id,current_workspace() or OWNER)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        if not key or not CampaignExecutionJob.query.filter_by(request_key=key).first():
            raise
        return enqueue_execution(kind, payload, key)
    view = _view(job)
    kick_execution_worker()
    return jsonify(view),202


def execution_status(job_id):
    expire_interrupted_jobs()
    job = db.session.get(CampaignExecutionJob, job_id)
    if not job:
        return jsonify({"error":"Campaign not found."}),404
    if job.status in {"queued", "running"}:
        kick_execution_worker()
    response = jsonify(_view(job))
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post('/api/demo/campaigns/jobs/<job_id>/cancel')
def cancel_campaign_job(job_id):
    from workspace_security import owns
    if not owns('campaign',job_id):return jsonify({'error':'Campaign not found.'}),404
    job=db.session.get(CampaignExecutionJob,job_id)
    if not job:return jsonify({'error':'Campaign not found.'}),404
    if job.status in {'queued','running'}:
        job.status='cancelled';job.error='CAMPAIGN_CANCELLED_REVIEW_IN_FLIGHT_EFFECTS';job.finished_at=datetime.utcnow()
        from src.progressive_campaign import CampaignBusinessTask
        CampaignBusinessTask.query.filter(CampaignBusinessTask.campaign_id==job_id,CampaignBusinessTask.status.in_(['queued','running'])).update({
            'status':'cancelled','error':'CAMPAIGN_CANCELLED','updated_at':datetime.utcnow(),'finished_at':datetime.utcnow()},synchronize_session=False)
        db.session.commit()
    return jsonify(_view(job))
