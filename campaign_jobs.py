"""Persisted campaign execution with atomic claims; interrupted sends are never replayed."""
import json
import secrets
import threading
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
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="campaign-execution")
_lock = threading.Lock()
_future = None


def process_next_execution_job():
    now = datetime.utcnow()
    # Execution can have external effects. A stale claim requires review, never requeue.
    CampaignExecutionJob.query.filter(CampaignExecutionJob.status == "running", CampaignExecutionJob.started_at < now-timedelta(minutes=60)).update({"status":"failed", "error":"EXECUTION_INTERRUPTED_REVIEW_REQUIRED", "result_http_status":500, "result_json":json.dumps({"ok":False,"reason":"EXECUTION_INTERRUPTED_REVIEW_REQUIRED"}), "finished_at":now})
    db.session.commit()
    job = CampaignExecutionJob.query.filter_by(status="queued").order_by(CampaignExecutionJob.created_at).first()
    if not job:
        return {"processed":0}
    job_id = job.id
    claimed = CampaignExecutionJob.query.filter_by(id=job_id, status="queued").update({"status":"running", "started_at":now})
    db.session.commit()
    if not claimed:
        return {"processed":0}
    try:
        import customer_demo as demo
        if job.kind == "acceptance":
            campaign=json.loads(job.payload_json).get('campaign')
            def report_progress(progress):
                # Persist visibility without triggering extra research or bypassing gates.
                job.result_json = json.dumps({"progress": progress}, sort_keys=True)
                db.session.commit()
            response = app.make_response(demo._run_acceptance(campaign, progress_callback=report_progress))
            result, code = response.get_json(), response.status_code
        else:
            result, stage, reason = demo._run_campaign(json.loads(job.payload_json))
            code = 200 if result else 500
            result = result or {"ok":False, "stage":stage, "reason":reason}
        job.result_json = json.dumps(result)
        job.result_http_status = code
        job.status = "completed" if code == 200 and result.get("ok") is True else "failed"
        job.error = "" if job.status == "completed" else str(result.get("reason") or "EXECUTION_FAILED")[:200]
    except Exception:
        app.logger.exception("CAMPAIGN_EXECUTION_FAILED")
        db.session.rollback()
        job = db.session.get(CampaignExecutionJob, job_id)
        job.status = "failed"
        job.error = "EXECUTION_FAILED_REVIEW_REQUIRED"
        job.result_http_status = 500
        job.result_json = json.dumps({"ok":False,"reason":job.error})
    job.finished_at = datetime.utcnow()
    db.session.commit()
    return {"processed":1, "job_id":job_id, "ok":job.status == "completed"}


def _worker():
    with app.app_context():
        try:
            while process_next_execution_job().get("processed"):
                pass
        finally:
            db.session.remove()


def kick_execution_worker():
    global _future
    with _lock:
        if _future is None or _future.done():
            _future = _pool.submit(_worker)


def _view(job):
    result = {"job_id":job.id, "status":job.status, "poll_url":"/api/demo/campaigns/jobs/"+job.id, "error":job.error}
    result["progress"] = (json.loads(job.result_json or "{}").get("progress") or {}) if job.status in {"queued", "running"} else {}
    if job.status in {"completed", "failed"}:
        result.update(result=json.loads(job.result_json or "{}"), result_http_status=job.result_http_status)
    return result


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
    db.session.add(job)
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
    job = db.session.get(CampaignExecutionJob, job_id)
    if not job:
        return jsonify({"error":"Campaign not found."}),404
    if job.status in {"queued", "running"}:
        kick_execution_worker()
    response = jsonify(_view(job))
    response.headers["Cache-Control"] = "no-store"
    return response
