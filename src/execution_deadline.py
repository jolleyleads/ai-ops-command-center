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
