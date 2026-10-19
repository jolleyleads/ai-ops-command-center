"""Database-backed read-only research jobs; no outreach is launched here."""
import json
import secrets
import threading
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from flask import jsonify, request
from app import app, db
from smart_search import _smart_search
from src.research_policy import research_budget_seconds, research_target_count, requested_target_count


class ResearchJob(db.Model):
    __tablename__="research_job"
    id=db.Column(db.String(48),primary_key=True)
    prompt_text=db.Column(db.Text,nullable=False)
    location=db.Column(db.String(200),default="")
    target_count=db.Column(db.Integer,default=10)
    status=db.Column(db.String(30),nullable=False,default="queued",index=True)
    result_json=db.Column(db.Text,default="{}")
    error=db.Column(db.String(200),default="")
    created_at=db.Column(db.DateTime,default=datetime.utcnow)
    started_at=db.Column(db.DateTime)
    finished_at=db.Column(db.DateTime)


with app.app_context():db.create_all()
_pool = None
_lock = threading.Lock()
_future = None
_pool_pid = None


def reset_worker_pool():
    """A preloaded Gunicorn fork must not inherit a dead executor or held lock."""
    global _pool, _lock, _future, _pool_pid
    _pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="deep-research")
    _lock = threading.Lock()
    _future = None
    _pool_pid = os.getpid()


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=reset_worker_pool)


def process_next_research_job():
    now=datetime.utcnow()
    # Recover work interrupted by a deploy. Jobs only research; no sends/bookings.
    ResearchJob.query.filter(ResearchJob.status=="running",ResearchJob.started_at<now-timedelta(minutes=10)).update({"status":"queued"})
    db.session.commit()
    job=ResearchJob.query.filter_by(status="queued").order_by(ResearchJob.created_at).first()
    if not job:return {"ok":True,"processed":0}
    job_id=job.id
    claimed=ResearchJob.query.filter_by(id=job_id,status="queued").update({"status":"running","started_at":now})
    db.session.commit()
    if not claimed:return {"ok":True,"processed":0}
    try:
        budget=research_budget_seconds(job.target_count)
        from src.execution_deadline import execution_scope
        def progress(details):
            previous=json.loads(db.session.get(ResearchJob,job_id).result_json or '{}').get('progress') or {}
            details={**previous,**details,'updated_at':datetime.utcnow().isoformat()+'Z'}
            changed=ResearchJob.query.filter_by(id=job_id,status='running',started_at=now).update(
                {'result_json':json.dumps({'progress':details})},synchronize_session=False)
            db.session.commit()
            if not changed:raise TimeoutError('Research cancelled or claim lost')
        with execution_scope(budget+30,progress):
            result=_smart_search(job.prompt_text,job.location,runtime_budget=budget,target_count=job.target_count)
        result_json=json.dumps(result)
        status="failed" if result.get("agent_error") else "completed"
        error="Research could not finish. Please try again." if status=="failed" else ""
    except Exception:
        app.logger.exception("BACKGROUND_RESEARCH_FAILED")
        db.session.rollback()
        result_json,status,error='{}','failed','Research could not finish. Please try again.'
    finished=ResearchJob.query.filter_by(id=job_id,status='running',started_at=now).update(
        {'result_json':result_json,'status':status,'error':error,'finished_at':datetime.utcnow()},synchronize_session=False)
    db.session.commit()
    return {"ok":status=="completed" and bool(finished),"processed":1,"job_id":job_id,"lease_lost":not bool(finished)}


def _worker():
    with app.app_context():
        try:
            while process_next_research_job().get("processed"):pass
        finally:db.session.remove()


def kick_worker():
    global _future
    if _pool_pid != os.getpid():
        reset_worker_pool()
    with _lock:
        if _future is None or _future.done():_future=_pool.submit(_worker)


@app.route("/api/research/jobs",methods=["POST"])
def create_research_job():
    data=request.get_json(silent=True) or {}
    query=str(data.get("query") or data.get("prompt") or "").strip()[:1000]
    if not query:return jsonify({"error":"Enter a search inquiry."}),400
    try:target=requested_target_count(data.get("target_count"))
    except (TypeError,ValueError) as exc:return jsonify({"error":str(exc),"maximum_results":20,"work_started":False}),422
    if ResearchJob.query.filter(ResearchJob.status.in_(["queued","running"])).count()>=5 or ResearchJob.query.filter(ResearchJob.created_at>datetime.utcnow()-timedelta(minutes=1)).count()>=5:
        return jsonify({"error":"Several searches are already running. Please try shortly."}),429
    job=ResearchJob(id=secrets.token_urlsafe(24),prompt_text=query,location=str(data.get("location") or "").strip()[:200],target_count=target)
    from workspace_security import claim, research_workspace
    db.session.add(job);claim("research",job.id,research_workspace(create=True));db.session.commit();job_id=job.id
    kick_worker()
    return jsonify({"job_id":job_id,"status":"queued","poll_url":"/api/research/jobs/"+job_id}),202


@app.route("/api/research/jobs/<job_id>",methods=["GET"])
def get_research_job(job_id):
    job=db.session.get(ResearchJob,job_id)
    if not job:return jsonify({"error":"Search not found."}),404
    payload={"job_id":job.id,"status":job.status,"target_count":job.target_count,"error":job.error}
    payload["progress"]=(json.loads(job.result_json or "{}").get("progress") or {})
    if job.status=="completed":payload["result"]=json.loads(job.result_json)
    if job.status in {"queued","running"}:kick_worker()
    response=jsonify(payload);response.headers["Cache-Control"]="no-store"
    return response


@app.route('/api/research/jobs/<job_id>/cancel',methods=['POST'])
def cancel_research_job(job_id):
    job=db.session.get(ResearchJob,job_id)
    if not job:return jsonify({'error':'Search not found.'}),404
    if job.status in {'queued','running'}:
        job.status='cancelled';job.error='Research cancelled';job.finished_at=datetime.utcnow();db.session.commit()
    return jsonify({'job_id':job.id,'status':job.status})
