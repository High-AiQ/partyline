"""Event-driven share capture and local stop-input ownership."""

import asyncio
import sys
import time

from PIL import Image


async def _stop_input(session, request, stopped):
    changes = session.control.input_changes
    while session.share is request:
        observed = changes.version
        if session.control.prompting:
            await changes.wait_after(observed)
            continue
        reading = asyncio.create_task(session.terminal.read(None))
        session.stop_read = reading
        changed = asyncio.create_task(changes.wait_after(observed))
        try:
            done, _ = await asyncio.wait((reading, changed), return_when=asyncio.FIRST_COMPLETED)
            if reading not in done or reading.cancelled():
                changed.result()
                continue  # a consent prompt now owns terminal input
            if reading.result() == 's':
                session.share = None
                session.accepted = False
                session.pending_id = None
                session.control.end('sharing stopped locally')
                await session.send('share_stopped', share_id=request['share_id'], reason='local')
                print('Sharing stopped: local', flush=True)
                stopped.set()
                return
        finally:
            reading.cancel()
            changed.cancel()
            await asyncio.gather(reading, changed, return_exceptions=True)
            if getattr(session, "stop_read", None) is reading:
                session.stop_read = None


class _UnavailableCapture:
    def start(self, on_frame, on_closed):
        raise RuntimeError("Event-driven screen capture is supported on Windows only; "
                           "macOS and Linux need follow-up")

    def stop(self):
        pass


class _WindowsCapture:
    """Adapter for windows-capture's GraphicsCaptureItem/FrameArrived implementation."""

    def __init__(self, request):
        from .windows_capture import window_for_region

        self.hwnd, self.bounds = window_for_region(request['region'])
        import ctypes
        if not ctypes.windll.user32.IsWindow(self.hwnd):
            raise RuntimeError("The shared window closed before capture started")
        from windows_capture import WindowsCapture

        self.capture = WindowsCapture(window_hwnd=self.hwnd, cursor_capture=True, draw_border=False)
        self.control = None

    def start(self, on_frame, on_closed):
        @self.capture.event
        def on_frame_arrived(frame, _control):
            image = Image.fromarray(frame.to_bgr()[..., ::-1].copy(), "RGB")
            on_frame(image, self.bounds)

        @self.capture.event
        def on_capture_closed():
            on_closed()

        self.control = self.capture.start_free_threaded()

    def stop(self):
        if self.control:
            self.control.stop()
            self.control.wait()
            self.control = None


def _capture_session(request):
    return _WindowsCapture(request) if sys.platform == "win32" else _UnavailableCapture()


def _region_image(image, bounds, region):
    """Crop a WGC window frame into the requested desktop rectangle, preserving its dimensions."""
    x = round(region['x'] - bounds[0])
    y = round(region['y'] - bounds[1])
    return image.crop((x, y, x + region['width'], y + region['height']))


async def capture(session, request, capture_factory=None, clock=time.monotonic):
    """Forward WGC frames as they arrive; rate-limit in the callback by dropping excess frames."""
    capture_factory = capture_factory or _capture_session
    stopped = asyncio.Event()
    closed = asyncio.Event()
    loop = asyncio.get_running_loop()
    source = capture_factory(request)
    input_task = asyncio.create_task(_stop_input(session, request, stopped))
    failure = loop.create_future()
    last_at = None
    pending = set()
    minimum_interval = 1 / request['max_fps']

    def arrived(image, bounds=(0, 0)):
        nonlocal last_at
        now = clock()
        if last_at is not None and now - last_at < minimum_interval:
            return
        last_at = now
        image = _region_image(image, bounds, request['region'])
        loop.call_soon_threadsafe(queue_frame, image)

    def queue_frame(image):
        if session.share is not request or closed.is_set() or pending:
            return

        async def deliver():
            try:
                await session.frame_from_capture(request, image)
            except Exception as exc:
                if not failure.done():
                    failure.set_exception(exc)
            finally:
                pending.discard(asyncio.current_task())

        task = asyncio.create_task(deliver())
        pending.add(task)

    def on_closed():
        loop.call_soon_threadsafe(closed.set)

    try:
        source.start(arrived, on_closed)
        stopped_task = asyncio.create_task(stopped.wait())
        closed_task = asyncio.create_task(closed.wait())
        try:
            done, _ = await asyncio.wait((stopped_task, closed_task, input_task, failure),
                                         return_when=asyncio.FIRST_COMPLETED)
            if input_task in done:
                input_task.result()
            elif failure in done:
                failure.result()
            elif closed_task in done and session.share is request:
                session.share = None
                session.accepted = False
                session.pending_id = None
                await session.send('share_stopped', share_id=request['share_id'], reason='window closed')
                print('Sharing stopped: window closed', flush=True)
        finally:
            stopped_task.cancel()
            closed_task.cancel()
            await asyncio.gather(stopped_task, closed_task, return_exceptions=True)
    finally:
        input_task.cancel()
        await asyncio.gather(input_task, return_exceptions=True)
        source.stop()
        if not failure.done():
            failure.cancel()
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
