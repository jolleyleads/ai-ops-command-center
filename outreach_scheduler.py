import os
import threading
import time

from app import app
# The Render cron imports this module directly instead of commercial_app.
# Bootstrap the persisted Google OAuth integration before gmail_outreach_state
# captures app.gmail_access_token at import time.
import gmail_connect  # noqa: F401
from gmail_outreach_state import process_durable_followups
from v1_orchestration import scan_real_inbound_replies

_INTERVAL_SECONDS = max(300, int(os.getenv("OUTREACH_SCHEDULER_SECONDS", "900")))
_started = False
_lock = threading.Lock()


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
        # Error text from Google's token endpoint is safe here; credentials/tokens are never included.
        app.logger.warning("GMAIL_OAUTH_TOKEN_PROBE ok=False type=%s detail=%s", type(exc).__name__, str(exc)[:300])


def run_scheduled_outreach_cycle():
    """Process real inbound replies before any follow-up work."""
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

    followups = process_durable_followups()
    app.logger.info(
        "OUTREACH_FOLLOWUP_SCHEDULER ok=%s tracked_threads=%s processed=%s",
        followups.get("ok"),
        followups.get("tracked_threads", 0),
        len(followups.get("processed") or []),
    )
    if not followups.get("ok"):
        app.logger.warning("OUTREACH_FOLLOWUP_SCHEDULER_ERROR %s", followups.get("error"))

    return {"ok": bool(inbound.get("ok")) and bool(followups.get("ok")), "inbound": inbound, "followups": followups}


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
