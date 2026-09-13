import os
import threading
import time

from app import app
from outreach_automation import process_followups

_INTERVAL_SECONDS = max(300, int(os.getenv("OUTREACH_SCHEDULER_SECONDS", "900")))
_started = False
_lock = threading.Lock()


def _loop():
    time.sleep(60)
    while True:
        try:
            with app.app_context():
                response = process_followups()
                app.logger.info("OUTREACH_FOLLOWUP_SCHEDULER ran status=%s", getattr(response, "status_code", 200))
        except Exception as exc:
            app.logger.exception("OUTREACH_FOLLOWUP_SCHEDULER_ERROR %s", type(exc).__name__)
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
