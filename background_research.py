"""Database-backed read-only research jobs; no outreach is launched here."""
import json
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from flask import jsonify, request
from app import app, db
from smart_search import _smart_search


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
_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix="deep-research")
_lock=threading.Lock()
_future=None


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
        budget=max(240,min(540,180+job.target_count*24))
        result=_smart_search(job.prompt_text,job.location,runtime_budget=budget,target_count=job.target_count)
        job.result_json=json.dumps(result)
        job.status="failed" if result.get("agent_error") else "completed"
        job.error="Research could not finish. Please try again." if job.status=="failed" else ""
    except Exception:
        app.logger.exception("BACKGROUND_RESEARCH_FAILED")
        db.session.rollback();job=db.session.get(ResearchJob,job_id)
        job.status="failed";job.error="Research could not finish. Please try again."
    job.finished_at=datetime.utcnow();db.session.commit()
    return {"ok":job.status=="completed","processed":1,"job_id":job.id}


def _worker():
    with app.app_context():
        try:
            while process_next_research_job().get("processed"):pass
        finally:db.session.remove()


def kick_worker():
    global _future
    with _lock:
        if _future is None or _future.done():_future=_pool.submit(_worker)


@app.route("/api/research/jobs",methods=["POST"])
def create_research_job():
    data=request.get_json(silent=True) or {}
    query=str(data.get("query") or data.get("prompt") or "").strip()[:1000]
    if not query:return jsonify({"error":"Enter a search inquiry."}),400
    try:target=max(1,min(int(data.get("target_count") or 10),20))
    except (TypeError,ValueError):return jsonify({"error":"Result count must be a number."}),400
    if ResearchJob.query.filter(ResearchJob.created_at>datetime.utcnow()-timedelta(minutes=1)).count()>=5:
        return jsonify({"error":"Several searches are already running. Please try shortly."}),429
    job=ResearchJob(id=secrets.token_urlsafe(24),prompt_text=query,location=str(data.get("location") or "").strip()[:200],target_count=target)
    db.session.add(job);db.session.commit();job_id=job.id
    kick_worker()
    return jsonify({"job_id":job_id,"status":"queued","poll_url":"/api/research/jobs/"+job_id}),202


@app.route("/api/research/jobs/<job_id>",methods=["GET"])
def get_research_job(job_id):
    job=db.session.get(ResearchJob,job_id)
    if not job:return jsonify({"error":"Search not found."}),404
    payload={"job_id":job.id,"status":job.status,"target_count":job.target_count,"error":job.error}
    if job.status=="completed":payload["result"]=json.loads(job.result_json)
    if job.status in {"queued","running"}:kick_worker()
    response=jsonify(payload);response.headers["Cache-Control"]="no-store"
    return response
