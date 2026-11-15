"""Collect nested screen operations without clocks crossing the helper/server boundary."""
import time
import math
from contextlib import contextmanager, asynccontextmanager
from contextvars import ContextVar
from functools import wraps

from .screen_timing_contract import HELPER, STOP
from .screen_bounded import bounded

clock = time.perf_counter
current = ContextVar('screen_timing', default=None)


@contextmanager
def phase(name):
    start = clock()
    try:
        yield
    finally:
        values = current.get()
        if values is not None:
            values[name] = round(values.get(name, 0) + max(0, clock() - start) * 1000, 3)


def helper(values):
    timing = current.get()
    if timing is not None and isinstance(values, dict):
        for key, value in values.items():
            if (key in HELPER and type(value) in (float, int) and math.isfinite(value)
                    and 0 <= value <= 86400000):
                name = 'helper_' + key
                timing[name] = round(timing.get(name, 0) + value, 3)
            elif key == 'barrier_stop' and value in STOP:
                timing['helper_barrier_stop'] = value


def timed(function):
    @wraps(function)
    async def run(*args, **kwargs):
        if current.get() is not None:
            return await function(*args, **kwargs)
        values, start = {}, clock()
        request = kwargs.get("request") or next((arg for arg in args if hasattr(arg, "scope")), None)
        received = request.scope.get("screen_received_at") if request is not None else None
        values["request_queue_ms"] = round(max(0, start - received) * 1000, 3) if received is not None else 0
        token = current.set(values)
        try:
            result = await function(*args, **kwargs)
            values['server_total_ms'] = round(max(0, clock() - start) * 1000, 3)
            result['timing'] = values
            return bounded(result) if result.get("source") == "cdp" else result
        finally:
            current.reset(token)
    return run


@asynccontextmanager
async def locked(lock):
    with phase("window_lock_ms"):
        await lock.acquire()
    try:
        yield
    finally:
        lock.release()
