"""Atomic per-browser/global request budgets for the shared public AI service."""
from contextlib import contextmanager
from datetime import datetime, timezone
import os
import sqlite3
import threading
from fitplate.model_client import ServiceError
from fitplate.visitors import current_visitor, data_root

_slots = threading.BoundedSemaphore(2)


def limit(name, default):
    try:
        value = int(os.environ.get(name, default))
        return value if value > 0 else default
    except (ValueError, TypeError):
        return default


def consume_request(identifier, day=None):
    root = data_root()
    root.mkdir(parents=True, exist_ok=True)
    day = day or datetime.now(timezone.utc).date().isoformat()
    with sqlite3.connect(root / 'ai_usage.sqlite3', timeout=10) as db:
        db.execute('CREATE TABLE IF NOT EXISTS requests (day TEXT, visitor TEXT, count INTEGER NOT NULL, PRIMARY KEY(day,visitor))')
        db.execute('BEGIN IMMEDIATE')
        own = db.execute('SELECT count FROM requests WHERE day=? AND visitor=?',(day,identifier)).fetchone()
        total = db.execute('SELECT coalesce(sum(count),0) FROM requests WHERE day=?',(day,)).fetchone()[0]
        if (own[0] if own else 0) >= limit('FITPLATE_VISITOR_DAILY_REQUESTS',30):
            raise ServiceError('Your daily AI allowance has been reached. You can still edit meals and use local calculations.')
        if total >= limit('FITPLATE_GLOBAL_DAILY_REQUESTS',300):
            raise ServiceError('The shared AI service has reached its daily allowance. Please try again tomorrow; local calculations remain available.')
        db.execute('INSERT INTO requests VALUES (?,?,1) ON CONFLICT(day,visitor) DO UPDATE SET count=count+1',(day,identifier))


@contextmanager
def request_slot():
    identifier = current_visitor()
    if not identifier:
        yield
        return
    if not _slots.acquire(blocking=False):
        raise ServiceError('The shared AI service is busy. Please try again shortly.')
    try:
        consume_request(identifier)
        yield
    finally:
        _slots.release()
