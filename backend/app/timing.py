"""Opt-in command timings; never records answers, usernames or session tokens."""
import json
import logging
import os
import time
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from uuid import uuid4

_current = ContextVar("room_timing", default=None)
logger = logging.getLogger("uvicorn.error")


@contextmanager
def command_timing(room_id, operation):
    if os.getenv("ROOM_TIMING_ENABLED", "false").lower() != "true":
        yield
        return
    record = {"event": "room_command_timing", "trace_id": uuid4().hex,
              "room_id": room_id, "operation": operation, "outcome": "ok"}
    token = _current.set(record)
    started = time.perf_counter()
    try:
        yield
    except BaseException as exc:
        record["outcome"] = type(exc).__name__
        raise
    finally:
        record["total_ms"] = round((time.perf_counter() - started) * 1000, 3)
        _current.reset(token)
        logger.info("room_command_timing %s", json.dumps(record, sort_keys=True))


def count(name):
    record = _current.get()
    if record is not None:
        record[name] = record.get(name, 0) + 1


@contextmanager
def span(name):
    record = _current.get()
    if record is None:
        yield
        return
    started = time.perf_counter()
    try:
        yield
    finally:
        record[name + "_ms"] = round(record.get(name + "_ms", 0) + (time.perf_counter() - started) * 1000, 3)
        count(name + "_count")


@asynccontextmanager
async def measured_room_lock(lock):
    with span("room_lock_wait"):
        await lock.acquire()
    try:
        with span("room_lock_hold"):
            yield
    finally:
        lock.release()
