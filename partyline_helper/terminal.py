"""One daemon reader: timed-out consent never leaves an input thread blocking exit."""
import asyncio
import queue
import re
import sys
import threading
import time


PROMPT_DELAY = 1.0
ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-_])")


def display_text(value):
    return "".join(char for char in ANSI.sub("", str(value)) if char.isprintable())[:120]


class Terminal:
    def __init__(self, clock=time.monotonic, sleep=asyncio.sleep, read_stdin=True):
        self.clock, self.sleep = clock, sleep
        self.lines = queue.Queue()
        if read_stdin:
            threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in sys.stdin:
            self.lines.put(line.strip().lower())

    def clear(self):
        while not self.lines.empty():
            self.lines.get_nowait()

    async def read(self, timeout=None):
        start = self.clock()
        while timeout is None or self.clock() - start < timeout:
            try:
                return self.lines.get_nowait()
            except queue.Empty:
                await self.sleep(0.05)
        return None

    async def consent(self, request, yes=False, timeout=60):
        self.clear()
        region = {key: request["region"][key] for key in ("x", "y", "width", "height")}
        print(f"\nSCREEN SHARE REQUEST\nRequested by: {display_text(request['requested_by'])}\n"
              f"Line: {display_text(request['line_name'])}\nOS region: {region}", flush=True)
        if yes:
            return True
        deadline = self.clock() + timeout
        print("Please wait 1 second; earlier input is ignored.", flush=True)
        await self.sleep(min(PROMPT_DELAY, timeout))
        self.clear()
        print("Share this region? [y/N] ", end="", flush=True)
        remaining = max(0, deadline - self.clock())
        return await self.read(remaining) == "y"
