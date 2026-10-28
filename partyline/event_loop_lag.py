"""Low-overhead, token-free event-loop stall warnings."""

import asyncio
from contextlib import suppress
import logging
import math
import os
import threading

from .loop_watchdog import Watchdog
from .periodic_timing import slowest

logger = logging.getLogger(__name__)


def _setting(name: str, default: float, minimum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
        return value if math.isfinite(value) and value >= minimum else default
    except ValueError:
        return default


async def _heartbeat(watchdog):
    while True:
        watchdog.beat()
        await asyncio.sleep(0.1)


async def monitor() -> None:
    interval = _setting('PARTYLINE_LOOP_LAG_INTERVAL', 0.1, 0.01)
    threshold = _setting('PARTYLINE_LOOP_LAG_THRESHOLD', 0.25, 0.0)
    cooldown = _setting('PARTYLINE_LOOP_LAG_COOLDOWN', 10.0, 0.0)
    loop = asyncio.get_running_loop()
    last_warning = float('-inf')
    watchdog = Watchdog(
        threading.get_ident(),
        threshold=_setting('PARTYLINE_LOOP_WATCHDOG_THRESHOLD', 0.3, 0.01),
        interval=_setting('PARTYLINE_LOOP_WATCHDOG_INTERVAL', 0.1, 0.01),
        cooldown=_setting('PARTYLINE_LOOP_WATCHDOG_COOLDOWN', 5.0, 0.0),
    )
    watchdog.start()
    heartbeat = asyncio.create_task(_heartbeat(watchdog))
    try:
        while True:
            expected = loop.time() + interval
            await asyncio.sleep(interval)
            now = loop.time()
            lag = now - expected
            if lag > threshold and now - last_warning >= cooldown:
                # Callback reprs can contain request URLs, tokens or message bodies.
                job = slowest(expected, now)
                if job:
                    logger.warning('event loop lag %.0f ms; periodic job %s %.0f ms',
                                   lag * 1000, job[0], job[1] * 1000)
                else:
                    logger.warning('event loop lag %.0f ms', lag * 1000)
                last_warning = now
    finally:
        watchdog.stop()
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat
        await asyncio.to_thread(watchdog.thread.join)
