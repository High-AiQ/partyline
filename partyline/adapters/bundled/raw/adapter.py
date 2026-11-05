"""A safe generic adapter for interactive programs without a transcript API."""

from __future__ import annotations

import asyncio
import collections
import re
import time

from partyline.adapters.base import Adapter
from partyline.attachment_view import cwd_git_digest

ANSI_RE = re.compile(
    r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|"
    r"\x1b[@-_]|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"
)


class RawAdapter(Adapter):
    """Flush ANSI-stripped terminal output after a short quiet period."""

    kind = "raw"
    QUIET_SECONDS = 1.2
    ECHO_WINDOW = 5.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._buffer: list[str] = []
        self._last_output = 0.0
        self._pending = False
        self._echo: collections.deque[str] = collections.deque()
        self._echo_deadline = 0.0
        self._carry = ""

    def _strip_echo(self, text: str) -> str:
        """Drop the terminal's echo of our own input, line by line."""
        if self._echo and time.monotonic() > self._echo_deadline:
            self._echo.clear()
        if not self._echo:
            text, self._carry = self._carry + text, ""
            return text
        *lines, tail = (self._carry + text).split("\n")
        out = []
        for line in lines:
            if self._echo and line.rstrip().endswith(self._echo[0]):
                self._echo.popleft()  # echoed input, possibly after a prompt
            else:
                out.append(line + "\n")
        self._carry = ""
        if self._echo:
            self._carry = tail  # may be the start of an echo still arriving
        else:
            out.append(tail)
        return "".join(out)

    async def on_output(self, data: bytes):
        text = ANSI_RE.sub("", data.decode("utf-8", errors="replace"))
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if text:
            text = self._strip_echo(text)
            if text:
                self._buffer.append(text)
            self._pending = True
            self._last_output = time.monotonic()

    def _end_echo_window(self) -> None:
        carry, self._carry = self._carry, ""
        if carry and not (self._echo and carry.rstrip().endswith(self._echo[0])):
            self._buffer.append(carry)
        self._echo.clear()

    async def _run(self):
        while self.alive() or self._buffer or self._pending:
            await asyncio.sleep(0.25)
            if (self._buffer or self._pending) and (
                time.monotonic() - self._last_output > self.QUIET_SECONDS
            ):
                self._end_echo_window()
                body = "".join(self._buffer).strip("\n")
                self._buffer.clear()
                self._pending = False
                if body.strip():
                    await self.post(self.att["name"], "agent", body)
                # Raw has no structured input transcript. Its only usable
                # boundary is a completed quiet-period output flush (even one
                # that held only our own echo); this is explicitly weaker than
                # a turn-end transcript record.
                boundary = self.att.get("credit_delivery_boundary")
                if boundary is not None:
                    await boundary()

    def format_digest(self, messages: list[dict]) -> str:
        mention = re.compile(rf"@{re.escape(self.att['name'])}\b[,:]?\s*", re.IGNORECASE)
        lines = "\n".join(
            mention.sub("", message["body"]).strip()
            for message in messages if message["sender_type"] != "system"
        )
        return "\n".join(part for part in (lines, cwd_git_digest(self.att["cwd"])) if part)

    async def send_keys(self, text: str):
        expected = [line.strip() for line in text.replace("\r", "\n").split("\n")]
        self._echo.extend(line for line in expected if line)
        self._echo_deadline = time.monotonic() + self.ECHO_WINDOW
        await self._write_all(text.encode() + b"\r")


PartylineAdapter = RawAdapter
