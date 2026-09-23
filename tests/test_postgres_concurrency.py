"""PostgreSQL-only concurrency and failure tests for operator audit integrity.

These tests use the disposable PostgreSQL service supplied by CI. They never
call Gmail or Calendar.
"""
import hashlib
import json
import os
import threading
from datetime import datetime

import psycopg2
import pytest


PG=os.environ.get("TEST_POSTGRES_URL")


pytestmark=pytest.mark.skipif(not PG,reason="TEST_POSTGRES_URL is required")


SCHEMA="""
DROP TABLE IF EXISTS concurrency_audit;
CREATE TABLE concurrency_audit(
  id BIGSERIAL PRIMARY KEY,
  action TEXT NOT NULL,
  previous_hash TEXT NOT NULL,
  event_hash TEXT NOT NULL UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def setup_module():
    if not PG:return
    with psycopg2.connect(PG) as conn:
        with conn.cursor() as cur:cur.execute(SCHEMA)


def reset():
    with psycopg2.connect(PG) as conn:
        with conn.cursor() as cur:cur.execute("TRUNCATE concurrency_audit RESTART IDENTITY")


def append(action, barrier=None, fail_after_insert=False):
    conn=psycopg2.connect(PG)
    try:
        with conn:
            with conn.cursor() as cur:
                # Same transaction-scoped serialization primitive used by production _audit.
                cur.execute("SELECT pg_advisory_xact_lock(%s)",(90421001,))
                cur.execute("SELECT event_hash FROM concurrency_audit ORDER BY id DESC LIMIT 1")
                row=cur.fetchone();prev=row[0] if row else ""
                created=datetime.utcnow().isoformat()
                event_hash=hashlib.sha256("|".join([prev,action,created]).encode()).hexdigest()
                cur.execute("INSERT INTO concurrency_audit(action,previous_hash,event_hash) VALUES(%s,%s,%s)",(action,prev,event_hash))
                if fail_after_insert:
                    raise RuntimeError("injected transaction failure")
        return True
    finally:
        conn.close()


def rows():
    with psycopg2.connect(PG) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id,action,previous_hash,event_hash FROM concurrency_audit ORDER BY id")
            return cur.fetchall()


def test_concurrent_writers_form_one_linear_chain():
    reset()
    count=12
    gate=threading.Barrier(count)
    errors=[]
    def worker(i):
        try:
            gate.wait(timeout=5)
            append(f"action-{i}")
        except Exception as exc:
            errors.append(repr(exc))
    threads=[threading.Thread(target=worker,args=(i,)) for i in range(count)]
    for t in threads:t.start()
    for t in threads:t.join(15)
    assert not errors
    data=rows()
    assert len(data)==count
    assert data[0][2]==""
    for previous,current in zip(data,data[1:]):
        assert current[2]==previous[3]
    assert len({r[3] for r in data})==count


def test_failed_transaction_leaves_no_partial_audit_row():
    reset()
    with pytest.raises(RuntimeError,match="injected"):
        append("must-rollback",fail_after_insert=True)
    assert rows()==[]


def test_failed_writer_does_not_break_next_chain_head():
    reset()
    append("first")
    with pytest.raises(RuntimeError):
        append("failed",fail_after_insert=True)
    append("second")
    data=rows()
    assert [r[1] for r in data]==["first","second"]
    assert data[1][2]==data[0][3]


def test_advisory_lock_is_transaction_scoped_after_rollback():
    reset()
    with pytest.raises(RuntimeError):
        append("failed-lock-holder",fail_after_insert=True)
    # If pg_advisory_xact_lock leaked beyond rollback, this call would block/hang.
    assert append("after-rollback") is True
    assert len(rows())==1
