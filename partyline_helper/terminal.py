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
    def __init__(self, clock=time.monotonic, sleep=asyncio.sleep, read_stdin=True, dialog=None):
        self.clock, self.sleep = clock, sleep
        self.lines = queue.Queue()
        # `dialog` (see consent_dialog.auto_dialog) replaces the y/N prompt when there is no terminal.
        self.dialog = dialog
        if read_stdin and dialog is None:
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
        if self.dialog:
            region_text = ", ".join(f"{key}={value}" for key, value in region.items())
            return await self.dialog(
                "Partyline screen share request",
                f"{display_text(request['requested_by'])} asks to share part of your screen "
                f"(line: {display_text(request['line_name'])}).\n\nRegion: {region_text}\n\n"
                "Share this region?", timeout=timeout, sleep=self.sleep)
        return await self.ask("Share this region? [y/N] ", timeout)

    async def ask(self, question, timeout=60, dialog=None):
        """The guarded y/N prompt; agent control uses it directly so --yes never applies.

        Without a terminal, `dialog` = (title, message) is asked in the native dialog instead,
        which has the same 1 s guard and timeout.
        """
        if self.dialog and dialog:
            return await self.dialog(*dialog, timeout=timeout, sleep=self.sleep)
        self.clear()
        deadline = self.clock() + timeout
        print("Please wait 1 second; earlier input is ignored.", flush=True)
        await self.sleep(min(PROMPT_DELAY, timeout))
        self.clear()
        print(question, end="", flush=True)
        remaining = max(0, deadline - self.clock())
        return await self.read(remaining) == "y"
