"""Event-driven helper fixtures: no wall-clock sleeps, polling or deadlines."""
import asyncio
import json
from collections import defaultdict
from unittest.mock import AsyncMock

from PIL import Image

from partyline_helper.client import serve as native_serve

REGION = dict(x=-100, y=0, width=200, height=100)
MONITOR = dict(id=1, **REGION, scale=1.5, primary=True)


def request(**kwargs):
    return dict(type="start_share", share_id="share", conv_id="conv", line_name="line",
                requested_by="person", region=REGION.copy(), max_fps=30, **kwargs)


async def checkpoint():
    """Yield through the ready queue without starting a real timer."""
    ready = asyncio.get_running_loop().create_future()
    asyncio.get_running_loop().call_soon(ready.set_result, None)
    await ready


class ManualTime:
    def __init__(self):
        self.now = 0.0
        self.waiters = []
        self.sleep_calls = asyncio.Queue()

    def __call__(self):
        return self.now

    async def sleep(self, delay):
        if delay <= 0:
            await checkpoint()
            return
        future = asyncio.get_running_loop().create_future()
        entry = (round(self.now + delay, 9), future)
        self.waiters.append(entry)
        self.sleep_calls.put_nowait(delay)
        try:
            await future
        finally:
            self.waiters.remove(entry)

    def advance(self, seconds):
        self.now = round(self.now + seconds, 9)
        for deadline, future in self.waiters:
            if deadline <= self.now and not future.done():
                future.set_result(None)


class FakeDesktop:
    def __init__(self):
        self.image = Image.new("RGB", (200, 100), "white")
        self.position = (-20, 30)
        self.grabs = []
        self.captured = asyncio.Queue()
        self.grabbed = asyncio.Event()

    def monitors(self):
        return [MONITOR.copy()]

    def grab(self, region):
        self.grabs.append(region)
        self.captured.put_nowait(region)
        self.grabbed.set()
        return self.image.copy()

    def pointer(self):
        return self.position


class FakeTerminal:
    def __init__(self, consent=True):
        self.answer = consent
        self.prompts = asyncio.Queue()
        self.consent = AsyncMock(side_effect=self._consent)
        self.lines = asyncio.Queue()
        self.waiting = asyncio.Queue()

    async def _consent(self, request, yes):
        self.prompts.put_nowait(request)
        if isinstance(self.answer, asyncio.Future):
            return await self.answer
        return self.answer

    def clear(self):
        pass

    async def read(self, timeout):
        self.waiting.put_nowait(timeout)
        return await self.lines.get()


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.sent_event = asyncio.Event()
        self.close_code = 1000
        self.messages = defaultdict(asyncio.Queue)
        self.binaries = asyncio.Queue()
        self.closed_event = asyncio.Event()

    async def send(self, value):
        message = value if isinstance(value, bytes) else json.loads(value)
        self.sent.append(message)
        self.sent_event.set()
        if isinstance(message, bytes):
            self.binaries.put_nowait(message)
        else:
            self.messages[message["type"]].put_nowait(message)

    async def next(self, kind):
        return await self.messages[kind].get()

    async def close(self, **kwargs):
        self.closed = kwargs
        self.closed_event.set()


async def serve(*args, clock=None, **kwargs):
    clock = clock or ManualTime()
    return await native_serve(*args, clock=clock, session_sleep=clock.sleep, **kwargs)
