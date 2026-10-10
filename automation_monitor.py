"""Persist worker health and expose actionable status to authenticated operators."""
import json
from datetime import datetime, timedelta
from flask import jsonify
from app import app, db


class AutomationHeartbeat(db.Model):
    __tablename__ = "automation_heartbeat"
    name = db.Column(db.String(50), primary_key=True)
    checked_at = db.Column(db.DateTime, nullable=False)
    ok = db.Column(db.Boolean, nullable=False)
    detail_json = db.Column(db.Text, nullable=False, default="{}")


with app.app_context():
    db.create_all()


def record_cycle(inbound, followups, research):
    for name, result in (("inbound", inbound), ("followups", followups), ("research", research)):
        row = db.session.get(AutomationHeartbeat, name)
        if row is None:
            row = AutomationHeartbeat(name=name)
            db.session.add(row)
        row.checked_at = datetime.utcnow()
        row.ok = result.get("ok") is True
        row.detail_json = json.dumps({"processed_count": len(result.get("processed") or []) if isinstance(result.get("processed"), list) else result.get("processed", 0), "error": str(result.get("error") or "")[:200]})
    db.session.commit()


def health_snapshot():
    from background_research import ResearchJob
    from outreach_automation import ExternalSideEffectCommand, OutreachLead
    cutoff = datetime.utcnow() - timedelta(minutes=15)
    workers = []
    for name in ("inbound", "followups", "research"):
        row = db.session.get(AutomationHeartbeat, name)
        workers.append({"name": name, "status": "missing" if row is None else "stale" if row.checked_at < cutoff else "healthy" if row.ok else "failed", "checked_at": row.checked_at.isoformat() if row else None})
    stalled = ResearchJob.query.filter(ResearchJob.status.in_(["queued", "running"]), ResearchJob.created_at < cutoff).count()
    uncertain = ExternalSideEffectCommand.query.filter_by(status="uncertain").count()
    replies = OutreachLead.query.filter(OutreachLead.last_error != "", OutreachLead.last_error.isnot(None)).count()
    return {"ok": all(x["status"] == "healthy" for x in workers) and not stalled and not uncertain, "workers": workers, "stalled_searches": stalled, "uncertain_deliveries": uncertain, "leads_needing_review": replies}


@app.route("/api/operator/automation-health")
def automation_health():
    from outreach_automation import _operator_authorized, _operator_session_authorized
    if not (_operator_authorized() or _operator_session_authorized()):
        return jsonify({"ok": False, "error": "operator authentication required"}), 401
    response = jsonify(health_snapshot())
    response.headers["Cache-Control"] = "no-store"
    return response
