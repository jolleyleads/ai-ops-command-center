"""Per-execution stage reporting and cooperative deadline checks before effects."""
from contextvars import ContextVar
from contextlib import contextmanager
import time

_context = ContextVar('execution_context', default=None)

@contextmanager
def execution_scope(seconds, callback=None):
    token = _context.set((time.monotonic()+seconds, callback))
    try:
        yield
    finally:
        _context.reset(token)


def checkpoint(stage, **details):
    context = _context.get()
    if context:
        deadline, callback = context
        if time.monotonic() >= deadline:
            raise TimeoutError('EXECUTION_DEADLINE_EXCEEDED_REVIEW_REQUIRED')
        if callback:
            callback({'stage':stage, **details})


@contextmanager
def hard_stage_limit(seconds,stage):
    """Interrupt even CPU-bound parsing inside the supervised Unix child only."""
    import os,signal,threading
    if os.getenv('AUTOMAKE_ISOLATED_EXECUTION')!='1' or threading.current_thread() is not threading.main_thread() or not hasattr(signal,'setitimer'):
        yield
        return
    previous_handler=signal.getsignal(signal.SIGALRM)
    previous_timer=signal.getitimer(signal.ITIMER_REAL)
    started=time.monotonic()
    def expired(signum,frame):
        # Stack frames contain code locations only, never fetched pages or locals.
        import traceback,logging
        locations=[f'{item.filename}:{item.lineno}:{item.name}' for item in traceback.extract_stack(frame)[-12:]]
        logging.getLogger(__name__).warning('STAGE_DEADLINE stage=%s stack=%s',stage,' > '.join(locations))
        raise TimeoutError(stage.upper()+'_DEADLINE_EXCEEDED')
    signal.signal(signal.SIGALRM,expired)
    limit=min(seconds,previous_timer[0]) if previous_timer[0] else seconds
    signal.setitimer(signal.ITIMER_REAL,limit)
    try:yield
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        signal.signal(signal.SIGALRM,previous_handler)
        if previous_timer[0]:
            signal.setitimer(signal.ITIMER_REAL,max(0.001,previous_timer[0]-(time.monotonic()-started)),previous_timer[1])
