import os
import threading
import time

from app import app
from gmail_outreach_state import process_durable_followups

_INTERVAL_SECONDS = max(300, int(os.getenv("OUTREACH_SCHEDULER_SECONDS", "900")))
_started = False
_lock = threading.Lock()


def _loop():
    time.sleep(60)
    while True:
        try:
            with app.app_context():
                result = process_durable_followups()
                app.logger.info(
                    "OUTREACH_FOLLOWUP_SCHEDULER ok=%s tracked_threads=%s processed=%s",
                    result.get("ok"),
                    result.get("tracked_threads", 0),
                    len(result.get("processed") or []),
                )
                if not result.get("ok"):
                    app.logger.warning("OUTREACH_FOLLOWUP_SCHEDULER_ERROR %s", result.get("error"))
        except Exception as exc:
            app.logger.exception("OUTREACH_FOLLOWUP_SCHEDULER_EXCEPTION %s", type(exc).__name__)
        time.sleep(_INTERVAL_SECONDS)


def start():
    global _started
    with _lock:
        if _started:
            return
        _started = True
        thread = threading.Thread(target=_loop, name="outreach-followup-scheduler", daemon=True)
        thread.start()


start()
