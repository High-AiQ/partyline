"""Delay measured on real traffic; an idle server runs none of this.

Nothing here wakes on a timer. Each instrumented operation reads the clock
when it starts and again when it finishes, records the duration, and logs a
warning when it ran longer than the threshold. A blocked event loop shows up
as the slow request, push or dispatch it delayed, so no probe is needed.

Names are fixed strings chosen by the code or route templates, never URLs,
query strings, message bodies or tokens, because log lines outlive requests.
"""

import faulthandler
import inspect
import logging
import math
import os
import signal
import sys
import time
from collections import deque

logger = logging.getLogger(__name__)

clock = time.monotonic  # replaced by tests; the only time source in this module


def _setting(name: str, default: float, minimum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
        return value if math.isfinite(value) and value >= minimum else default
    except ValueError:
        return default


# The old loop-lag monitor's defaults: warn above 250 ms, at most once per 10 s per name.
THRESHOLD = _setting('PARTYLINE_SLOW_OP_THRESHOLD', 0.25, 0.0)
COOLDOWN = _setting('PARTYLINE_SLOW_OP_COOLDOWN', 10.0, 0.0)
MAX_NAMES = 256  # route templates and fixed names; anything past this shares one bucket

_stats: dict[str, dict] = {}
_last_warning: dict[str, float] = {}
_recent_slow = deque(maxlen=64)


def record(name: str, elapsed: float) -> None:
    """Count one finished operation; warn when slow, rate-limited per name."""
    if name not in _stats and len(_stats) >= MAX_NAMES:
        name = 'other'
    stat = _stats.setdefault(name, {'count': 0, 'slow': 0, 'max': 0.0})
    stat['count'] += 1
    stat['max'] = max(stat['max'], elapsed)
    if elapsed <= THRESHOLD:
        return
    stat['slow'] += 1
    now = clock()
    _recent_slow.append((name, elapsed))
    if now - _last_warning.get(name, -math.inf) >= COOLDOWN:
        _last_warning[name] = now
        logger.warning('slow operation %s took %.0f ms', name, elapsed * 1000)


async def awaited(name: str, awaitable):
    """Await one operation and time it, whether it finishes or raises."""
    began = clock()
    try:
        return await awaitable
    finally:
        record(name, clock() - began)


async def pushed(kind: str, awaitable):
    """Time one websocket send, whether it completes or fails."""
    return await awaited(f'push {kind}', awaitable)


# Everything an adapter calls to hand a transcript event to the runtime. The runtime
# supplies these (constructor arguments and att callbacks), so wrapping them once in the
# base adapter covers every adapter, bundled or imported, with no per-tail timers.
CALLBACK_KEYS = ('on_process_exit', 'on_provider_error', 'on_compaction', 'post_resume_record',
                 'on_transcript_claimed', 'confirm_delivery_ids', 'credit_delivery_boundary',
                 'repool_message_ids', 'mark_transcript_delivery', 'startup_attention')


class Timed:
    """A runtime callback whose every call is timed; other attributes reach the callable."""

    def __init__(self, name: str, fn):
        self.name, self.fn = name, fn

    def __call__(self, *args, **kwargs):
        began = clock()
        try:
            result = self.fn(*args, **kwargs)
        except BaseException:
            record(self.name, clock() - began)
            raise
        if not inspect.isawaitable(result):
            record(self.name, clock() - began)
            return result
        return self._finish(result, began)

    async def _finish(self, pending, began):
        try:
            return await pending
        finally:
            record(self.name, clock() - began)

    def __getattr__(self, attribute):
        return getattr(self.fn, attribute)


def callback(att: dict, key: str, fn):
    """Wrap a runtime callback as `dispatch <adapter> <key>`; sync or awaitable, once only."""
    if fn is None or isinstance(fn, Timed):
        return fn
    return Timed(f"dispatch {att.get('adapter', 'adapter')} {key}", fn)


class TimedAtt(dict):
    """An attachment dict that hands out its runtime callbacks timed, however they were set."""

    def __getitem__(self, key):
        value = super().__getitem__(key)
        return callback(self, key, value) if key in CALLBACK_KEYS and callable(value) else value

    def get(self, key, default=None):
        return self[key] if key in self else default


def stats() -> dict[str, dict]:
    """Per-name count, slow count and longest duration since start."""
    return {name: dict(stat) for name, stat in _stats.items()}


def recent_slow() -> list[tuple[str, float]]:
    return list(_recent_slow)


def reset() -> None:
    _stats.clear()
    _last_warning.clear()
    _recent_slow.clear()


class OpTimingMiddleware:
    """Time each HTTP request from receipt to the start of its response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        began = clock()
        done = False

        def finish():
            nonlocal done
            if done:
                return
            done = True
            # Route templates such as /api/hooks/{att_id}/{token}, never the request URL.
            route = getattr(scope.get('route'), 'path', None)
            record(f"{scope['method']} {route or 'unrouted'}", clock() - began)

        async def timed_send(message):
            if message['type'] == 'http.response.start':
                finish()
            await send(message)

        try:
            await self.app(scope, receive, timed_send)
        finally:
            finish()


def install(app) -> None:
    app.add_middleware(OpTimingMiddleware)


def register_stack_dump() -> bool:
    """SIGUSR1 prints every thread's stack to stderr, even from a wedged loop.

    The signal is the manual trigger that replaces the old watchdog thread.
    Frames show code locations only, never argument values.
    """
    if not hasattr(signal, 'SIGUSR1'):
        return False
    try:
        faulthandler.register(signal.SIGUSR1, file=sys.stderr, all_threads=True)
    except (OSError, ValueError, RuntimeError, AttributeError):
        return False  # stderr without a file descriptor, or not the main thread
    return True
