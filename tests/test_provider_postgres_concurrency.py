"""Exercise the real account lease functions on CI's disposable PostgreSQL."""
import os
import threading
import time
from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine, delete, select, update
from src import hunter_mailbox as hunter

PG=os.getenv('TEST_POSTGRES_URL')
pytestmark=pytest.mark.skipif(not PG,reason='TEST_POSTGRES_URL is required')


@pytest.fixture
def engine(monkeypatch):
    engine=create_engine(PG)
    table=hunter.HunterAccountGuard.__table__
    table.create(engine,checkfirst=True)
    with engine.begin() as connection:connection.execute(delete(table))
    monkeypatch.setattr(hunter,'db',SimpleNamespace(engine=engine))
    yield engine
    with engine.begin() as connection:connection.execute(delete(table))
    engine.dispose()


def test_real_concurrent_account_claims_have_one_owner(engine):
    barrier=threading.Barrier(6)
    results=[]
    def worker(index):
        barrier.wait(timeout=10)
        results.append(hunter._claim_account('concurrency@example.test',str(index),time.time()))
    threads=[threading.Thread(target=worker,args=(i,)) for i in range(6)]
    for thread in threads:thread.start()
    for thread in threads:thread.join(15)
    assert all(not thread.is_alive() for thread in threads)
    assert len(results)==6
    assert sum(not reason for _,reason in results)==1
    assert sum(reason=='HUNTER_CHECK_IN_PROGRESS' for _,reason in results)==5


def test_old_account_owner_cannot_clear_newer_quota_pause(engine):
    key,reason=hunter._claim_account('fencing@example.test','old',time.time())
    assert not reason
    future=time.time()+3600
    table=hunter.HunterAccountGuard.__table__
    with engine.begin() as connection:
        connection.execute(update(table).where(table.c.key==key).values(
            lease_token='new',expires_at=future,reason='HUNTER_FREE_QUOTA_EXHAUSTED'))
    hunter._release_account(key,'old',[])
    with engine.connect() as connection:
        row=connection.execute(select(table).where(table.c.key==key)).mappings().one()
    assert row['lease_token']=='new' and row['expires_at']==future
    assert row['reason']=='HUNTER_FREE_QUOTA_EXHAUSTED'
