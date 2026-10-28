"""Low-overhead, token-free event-loop stall warnings."""

import asyncio
import logging
import math
import os

logger = logging.getLogger(__name__)


def _setting(name: str, default: float, minimum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
        return value if math.isfinite(value) and value >= minimum else default
    except ValueError:
        return default


async def monitor() -> None:
    interval = _setting('PARTYLINE_LOOP_LAG_INTERVAL', 0.1, 0.01)
    threshold = _setting('PARTYLINE_LOOP_LAG_THRESHOLD', 0.25, 0.0)
    cooldown = _setting('PARTYLINE_LOOP_LAG_COOLDOWN', 10.0, 0.0)
    loop = asyncio.get_running_loop()
    last_warning = float('-inf')
    while True:
        expected = loop.time() + interval
        await asyncio.sleep(interval)
        now = loop.time()
        lag = now - expected
        if lag > threshold and now - last_warning >= cooldown:
            # Callback reprs can contain request URLs, tokens or message bodies.
            logger.warning('event loop lag %.0f ms', lag * 1000)
            last_warning = now
