import os
import threading
import time

from app import app
from gmail_outreach_state import process_durable_followups
from v1_orchestration import scan_real_inbound_replies

_INTERVAL_SECONDS = max(300, int(os.getenv("OUTREACH_SCHEDULER_SECONDS", "900")))
_started = False
_lock = threading.Lock()


def run_scheduled_outreach_cycle():
    """Process real inbound replies before any follow-up work.

    Reply processing is intentionally first so a newly received reply can stop
    follow-up activity and, when classified as interested, use the existing
    persisted-reply route for Calendar availability and booking.
    """
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


# Production uses the Render cron job. In-process scheduling is opt-in only
# for environments that intentionally do not run the cron service.
if os.getenv("OUTREACH_INPROCESS_SCHEDULER", "0").strip() == "1":
    start()
