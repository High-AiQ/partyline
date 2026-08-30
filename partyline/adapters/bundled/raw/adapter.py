"""A safe generic adapter for interactive programs without a transcript API."""

from __future__ import annotations

import asyncio
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._buffer: list[str] = []
        self._last_output = 0.0

    async def on_output(self, data: bytes):
        text = ANSI_RE.sub("", data.decode("utf-8", errors="replace"))
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if text:
            self._buffer.append(text)
            self._last_output = time.monotonic()

    async def _run(self):
        while self.alive() or self._buffer:
            await asyncio.sleep(0.25)
            if self._buffer and time.monotonic() - self._last_output > self.QUIET_SECONDS:
                body = "".join(self._buffer).strip("\n")
                self._buffer.clear()
                if body.strip():
                    await self.post(self.att["name"], "agent", body)

    def format_digest(self, messages: list[dict]) -> str:
        mention = re.compile(rf"@{re.escape(self.att['name'])}\b[,:]?\s*", re.IGNORECASE)
        lines = "\n".join(
            mention.sub("", message["body"]).strip()
            for message in messages if message["sender_type"] != "system"
        )
        return "\n".join(part for part in (lines, cwd_git_digest(self.att["cwd"])) if part)

    async def send_keys(self, text: str):
        await self._write_all(text.encode() + b"\r")


PartylineAdapter = RawAdapter
