"""PostgreSQL connection hardening for Render/Gunicorn background work.

This module does not contain credentials. It configures SQLAlchemy to validate
connections before checkout and to discard stale/broken DBAPI connections.
"""
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app import app, db


@event.listens_for(Engine, "engine_connect")
def _validate_connection(connection):
    # pool_pre_ping is the preferred mechanism; this listener is intentionally
    # empty and exists only so this module can be imported safely before the
    # application initializes its background scheduler.
    return None


with app.app_context():
    # Dispose anything inherited/stale, then make every future checkout verify
    # liveness. recycle limits how long a pooled SSL connection is reused.
    engine = db.engine
    engine.dispose()
    engine.pool._pre_ping = True
    if hasattr(engine.pool, "_recycle"):
        engine.pool._recycle = 240
    app.logger.warning("DATABASE_POOL_HARDENED pre_ping=True recycle=240")
