"""Bound concurrent AI requests without per-visitor or daily allowances."""
from contextlib import contextmanager
import threading
from fitplate.model_client import ServiceError
from fitplate.visitors import current_visitor

_slots = threading.BoundedSemaphore(2)


def consume_request(identifier, day=None):
    """Compatibility hook; historical allowance settings no longer restrict requests."""
    return None


@contextmanager
def request_slot():
    if not current_visitor():
        yield
        return
    if not _slots.acquire(blocking=False):
        raise ServiceError('The shared AI service is busy. Please try again shortly.')
    try:
        yield
    finally:
        _slots.release()
