"""Sample the event-loop thread without waiting for the event loop to run."""

import logging
import os
import sys
import threading
import time

logger = logging.getLogger(__name__)
_PACKAGE = os.path.dirname(__file__)


def stack(thread_id):
    """Only code locations, never frame values or source text."""
    frame = sys._current_frames().get(thread_id)
    locations = []
    while frame is not None and len(locations) < 12:
        code = frame.f_code
        filename = os.path.abspath(code.co_filename)
        if filename.startswith(_PACKAGE + os.sep):
            name = os.path.relpath(filename, _PACKAGE)
        else:
            name = '<external>'
        function = code.co_name if code.co_name.isidentifier() else '<code>'
        locations.append(f'{name}:{function}:{frame.f_lineno}')
        frame = frame.f_back
    return ' '.join(locations)


class Watchdog:
    def __init__(self, thread_id, *, threshold=0.3, interval=0.1, cooldown=5.0):
        self.thread_id = thread_id
        self.threshold = threshold
        self.interval = interval
        self.cooldown = cooldown
        self.heartbeat = time.monotonic()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name='event-loop-watchdog', daemon=True)

    def start(self):
        self.thread.start()

    def beat(self):
        self.heartbeat = time.monotonic()

    def stop(self):
        self.stop_event.set()

    def _run(self):
        last_warning = float('-inf')
        while not self.stop_event.wait(self.interval):
            now = time.monotonic()
            lag = now - self.heartbeat
            if lag >= self.threshold and now - last_warning >= self.cooldown:
                logger.warning('event loop watchdog %.0f ms stack %s', lag * 1000,
                               stack(self.thread_id))
                last_warning = now
