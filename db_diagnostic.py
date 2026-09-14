import os
from urllib.parse import urlparse

from app import app, db


def log_database_status():
    configured = bool(os.getenv("DATABASE_URL"))
    dialect = "unknown"
    host = ""
    try:
        with app.app_context():
            engine = db.engine
            dialect = engine.url.get_backend_name()
            host = engine.url.host or ""
    except Exception as exc:
        app.logger.warning(
            "DATABASE_DIAGNOSTIC configured=%s error=%s",
            configured,
            type(exc).__name__,
        )
        return

    if not host and os.getenv("DATABASE_URL"):
        try:
            host = urlparse(os.getenv("DATABASE_URL")).hostname or ""
        except Exception:
            host = ""

    app.logger.warning(
        "DATABASE_DIAGNOSTIC configured=%s dialect=%s host=%s",
        configured,
        dialect,
        host or "local",
    )


log_database_status()
