"""Event-driven helper fixtures: no wall-clock sleeps, polling or deadlines."""
import asyncio
import json
from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import AsyncMock

from PIL import Image

from partyline_helper.client import serve as native_serve
from partyline_helper.inputs import key_name

REGION = dict(x=-100, y=0, width=200, height=100)
MONITOR = dict(id=1, **REGION, scale=1.5, primary=True)


def request(**kwargs):
    return dict(type="start_share", share_id="share", conv_id="conv", line_name="line",
                requested_by="person", region=REGION.copy(), max_fps=30, **kwargs)


async def checkpoint():
    """Yield through the ready queue without starting a real timer."""
    ready = asyncio.get_running_loop().create_future()
    asyncio.get_running_loop().call_soon(lambda: ready.done() or ready.set_result(None))
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
        self.control_answer = False
        self.asks = asyncio.Queue()
        self.dialogs = []
        self.box_answer = (False, False)  # what ask_box returns, or a Future of it
        self.boxes = []

    async def _consent(self, request, yes):
        self.prompts.put_nowait(request)
        if isinstance(self.answer, asyncio.Future):
            return await self.answer
        return self.answer

    def clear(self):
        pass

    async def ask(self, question, dialog=None):
        self.asks.put_nowait(question)
        self.dialogs.append(dialog)
        if isinstance(self.control_answer, asyncio.Future):
            return await self.control_answer
        return self.control_answer

    async def ask_box(self, question, timeout=60, dialog=None, box=None):
        self.asks.put_nowait(question)
        self.dialogs.append(dialog)
        self.boxes.append(box)
        if isinstance(self.box_answer, asyncio.Future):
            return await self.box_answer
        return self.box_answer

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


class AutoTime(ManualTime):
    """Every sleep advances virtual time at once: loops progress without real waiting."""

    async def sleep(self, delay):
        self.now = round(self.now + max(0, delay), 9)
        await checkpoint()


X11_CONTROL_CODES = {"\n": "enter", "\r": "enter", "\t": "tab"}


class FakeInputs:
    """Records injected input and moves the fake pointer like a real controller would."""

    def __init__(self, desktop, fail=None):
        self.desktop, self.fail = desktop, fail
        self.calls = []
        self.on_key = None
        self.on_type = None  # called with each typed character, e.g. to press a physical key mid-text
        self.x11 = None  # "notice-first" or "echo-first": replay pynput's X11 listener events
        self.stopped = False

    def __call__(self, desktop):
        if self.fail == "init":
            raise RuntimeError("Agent control needs permission.")
        return self

    def move(self, x, y):
        self.calls.append(("move", x, y))
        self.desktop.position = (x, y)

    def press(self, button):
        self.calls.append(("press", button))

    def release(self, button):
        self.calls.append(("release", button))

    def click(self, button, count):
        self.calls.append(("click", button, count))

    def scroll(self, dx, dy):
        self.calls.append(("scroll", dx, dy))

    def type(self, text):
        self.calls.append(("type", text))
        self.native([X11_CONTROL_CODES.get(text, text)])
        if self.on_type:
            self.on_type(text)

    def key(self, names):
        self.calls.append(("key", names))
        self.native(list(names))

    def native(self, names):
        """pynput/keyboard/_xorg.py: each press and release reaches the listener flagged through
        _on_fake_event; named keys go by XTest, whose RECORD echo also arrives, unflagged;
        characters go by XSendEvent (flagged, Shift in the event state, no Shift press)."""
        if not self.x11 or not self.on_key:
            return
        for down, order in ((True, names), (False, names[::-1])):
            for name in order:
                notice = [(name.lower() if len(name) == 1 else name, True, down)]
                echo = [(self.echo_name(name, names), False, down)] if len(name) > 1 else []
                for event in (notice + echo if self.x11 == "notice-first" else echo + notice):
                    self.on_key(*event)

    def listen(self, on_key):
        if self.fail == "listen":
            raise RuntimeError("The kill-switch key listener could not start.")
        self.on_key = on_key

    @staticmethod
    def echo_name(name, names):
        """The RECORD echo is read back through the keymap: shifted Tab is ISO_Left_Tab, an
        unnamed KeyCode, which inputs.key_name must still call tab."""
        if name == "tab" and "shift" in names:
            return key_name(SimpleNamespace(vk=0xFE20, char=None))
        return name

    def stop(self):
        self.stopped = True
