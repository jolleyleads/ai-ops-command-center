import os
import threading
import time
import uuid
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError

from app import app, db
# The Render cron imports this module directly instead of commercial_app.
# Bootstrap the persisted Google OAuth integration before Gmail consumers run.
import gmail_connect  # noqa: F401
import gmail_outreach_state
import outreach_automation
from gmail_outreach_state import process_durable_followups
from v1_orchestration import scan_real_inbound_replies

# These modules import gmail_access_token by value. Bind them explicitly to the
# persisted-refresh-token-aware resolver so cron workers cannot retain app.py's
# legacy environment-only function reference.
gmail_outreach_state.gmail_access_token = gmail_connect.gmail_access_token
outreach_automation.gmail_access_token = gmail_connect.gmail_access_token

_INTERVAL_SECONDS = max(300, int(os.getenv("OUTREACH_SCHEDULER_SECONDS", "900")))
_started = False
_lock = threading.Lock()


class SchedulerLease(db.Model):
    __tablename__ = 'scheduler_lease'
    name = db.Column(db.String(50), primary_key=True)
    token = db.Column(db.String(64), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)


with app.app_context():
    db.create_all()


def _claim_cycle():
    now, token = datetime.utcnow(), uuid.uuid4().hex
    try:
        row = db.session.get(SchedulerLease, 'outreach')
        if row:
            claimed = SchedulerLease.query.filter_by(name='outreach').filter(
                SchedulerLease.expires_at <= now
            ).update({'token': token, 'expires_at': now+timedelta(minutes=30)}, synchronize_session=False)
            if not claimed:
                db.session.rollback()
                return ''
        else:
            db.session.add(SchedulerLease(name='outreach', token=token, expires_at=now+timedelta(minutes=30)))
        db.session.commit()
        return token
    except IntegrityError:
        db.session.rollback()
        return ''


def _oauth_diagnostics():
    """Return safe diagnostics only: never log tokens or secrets."""
    try:
        row = gmail_connect._stored_connection()
        stored = bool(row and (row.refresh_token or "").strip())
        stored_email = (row.email or "").strip() if row else ""
    except Exception as exc:
        stored = False
        stored_email = ""
        app.logger.warning("GMAIL_OAUTH_DIAGNOSTIC_DB_ERROR type=%s", type(exc).__name__)
    legacy = bool(os.getenv("GOOGLE_REFRESH_TOKEN", "").strip())
    direct = bool(os.getenv("GMAIL_ACCESS_TOKEN", "").strip())
    app.logger.warning(
        "GMAIL_OAUTH_DIAGNOSTIC stored_refresh=%s stored_email=%s legacy_refresh=%s direct_access=%s database_url=%s",
        stored,
        stored_email or "missing",
        legacy,
        direct,
        "present" if os.getenv("DATABASE_URL", "").strip() else "missing",
    )
    try:
        gmail_connect.gmail_access_token()
        app.logger.warning("GMAIL_OAUTH_TOKEN_PROBE ok=True")
    except Exception as exc:
        app.logger.warning("GMAIL_OAUTH_TOKEN_PROBE ok=False type=%s", type(exc).__name__)


def _run_scheduled_outreach_cycle():
    """Process real inbound replies before any follow-up work."""
    # Standalone cron must use the same durable sender as the web application.
    import gmail_reconciliation  # noqa: F401
    _oauth_diagnostics()
    inbound = scan_real_inbound_replies()
    app.logger.info(
        "OUTREACH_INBOUND_SCHEDULER ok=%s checked=%s processed=%s",
        inbound.get("ok"),
        inbound.get("checked", 0),
        len(inbound.get("processed") or []),
    )
    if not inbound.get("ok"):
        app.logger.warning("OUTREACH_INBOUND_SCHEDULER_ERROR %s", inbound.get("processed"))

    # Never deliver follow-ups while inbox reads are failing.
    followups = outreach_automation.process_due_followups() if inbound.get("ok") else {"ok":False,"processed":[],"error":"INBOUND_SCAN_FAILED"}
    legacy_followups = process_durable_followups() if inbound.get("ok") else {"ok":False,"processed":[]}
    # This durable cron also resumes searches after a web process restart,
    # even when the customer has closed the page. Research never sends mail.
    from background_research import process_next_research_job
    from production_smoke import run_configured_smoke
    smoke=run_configured_smoke()
    research = process_next_research_job()
    from lead_recovery import process_recoverable_leads
    recovery = process_recoverable_leads()
    from automation_monitor import record_cycle
    record_cycle(inbound, followups, research, recovery)
    if smoke.get("enabled"):
        app.logger.warning("PRODUCTION_SMOKE_STATE %s",smoke)
    app.logger.info(
        "OUTREACH_FOLLOWUP_SCHEDULER ok=%s tracked_threads=%s processed=%s",
        followups.get("ok"),
        followups.get("tracked_threads", 0),
        len(followups.get("processed") or []),
    )
    if not followups.get("ok"):
        app.logger.warning("OUTREACH_FOLLOWUP_SCHEDULER_ERROR %s", followups.get("error"))

    return {"ok": bool(inbound.get("ok")) and bool(followups.get("ok")) and bool(legacy_followups.get("ok")) and bool(research.get("ok")) and bool(recovery.get("ok")), "inbound": inbound, "followups": followups, "legacy_followups":legacy_followups, "research":research, "lead_recovery":recovery}


def run_scheduled_outreach_cycle():
    token = _claim_cycle()
    if not token:
        return {'ok': True, 'duplicate_cycle_suppressed': True}
    try:
        return _run_scheduled_outreach_cycle()
    except Exception as exc:
        db.session.rollback()
        from automation_monitor import record_cycle
        failure = {'ok': False, 'error': 'SCHEDULER_' + type(exc).__name__.upper()}
        record_cycle(failure, failure, failure, failure)
        return failure
    finally:
        db.session.rollback()
        SchedulerLease.query.filter_by(name='outreach', token=token).update(
            {'expires_at': datetime.utcnow()}, synchronize_session=False)
        db.session.commit()


def _loop():
    time.sleep(60)
    while True:
        try:
            with app.app_context():
                run_scheduled_outreach_cycle()
        except Exception as exc:
            app.logger.exception("OUTREACH_SCHEDULER_EXCEPTION %s", type(exc).__name__)
        time.sleep(_INTERVAL_SECONDS)


def start():
    global _started
    with _lock:
        if _started:
            return
        _started = True
        thread = threading.Thread(target=_loop, name="outreach-scheduler", daemon=True)
        thread.start()


if os.getenv("OUTREACH_INPROCESS_SCHEDULER", "0").strip() == "1":
    start()
