"""A preloaded process cannot carry running Future/Lock state into a new PID."""
import os
import pytest
import commercial_app
import campaign_jobs
import background_research

@pytest.mark.parametrize('module,kick',[ (campaign_jobs,'kick_execution_worker'),(background_research,'kick_worker') ])
def test_new_process_discards_inherited_future_and_lock(monkeypatch,module,kick):
    calls=[]
    class InheritedLock:
        def __enter__(self):pytest.fail('Used an inherited lock')
        def __exit__(self,*args):pass
    class InheritedFuture:
        def done(self):pytest.fail('Used an inherited Future')
    class NewFuture:
        def done(self):return False
    class Executor:
        def __init__(self,**kwargs):pass
        def submit(self,worker):calls.append(worker);return NewFuture()
    monkeypatch.setattr(module,'_pool_pid',-1)
    monkeypatch.setattr(module,'_lock',InheritedLock())
    monkeypatch.setattr(module,'_future',InheritedFuture())
    monkeypatch.setattr(module,'ThreadPoolExecutor',Executor)
    # Also restore the executor after this test, so later real workers stay real.
    monkeypatch.setattr(module,'_pool',None)
    getattr(module,kick)()
    assert module._pool_pid==os.getpid() and len(calls)==1
    getattr(module,kick)()
    assert len(calls)==1
