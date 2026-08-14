"""Adapter for Grok Build's interactive terminal.

Grok accepts a caller-generated UUID for a fresh interactive session. Its
JSONL transcript therefore has an exact, attachment-owned location rather
than needing unsafe discovery by working directory or modification time.
"""

from __future__ import annotations

import asyncio
import glob
import os
from pathlib import Path

from partyline.adapters import Adapter


class PartylineAdapter(Adapter):
    kind = "grok"
    POLL_SECONDS = 0.5
    TRANSCRIPT_TIMEOUT = 45.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Attachment ids are server-generated UUIDs. Passing one straight to
        # Grok pins a fresh session to this attachment, without another source
        # of identity that could diverge from the stored attachment record.
        stored_session = str(self.att.get("cli_session") or "").strip()
        self._session_id = stored_session if self.resume else self.att["id"]
        self._resume_offset: int | None = None

    def _transcript(self) -> Path | None:
        """Return the one transcript whose caller-pinned UUID matches."""
        pattern = os.path.expanduser(
            f"~/.grok/sessions/*/{self._session_id}/chat_history.jsonl"
        )
        paths = [Path(path) for path in glob.glob(pattern)]
        return paths[0] if len(paths) == 1 else None

    async def start(self):
        if self.resume:
            if not self._session_id:
                raise ValueError("Grok resume requires the stored session UUID")
            path = self._transcript()
            if path is not None:
                try:
                    self._resume_offset = path.stat().st_size
                except OSError:
                    pass
        await super().start()

    def build_command(self) -> list[str]:
        cmd = list(self.att["command"]) or [
            "grok", "--permission-mode", "bypassPermissions",
        ]
        if any(arg == "-s" or arg.startswith("--session-id") for arg in cmd):
            raise ValueError("Grok's session ID is managed by Partyline")
        if self.resume:
            if not self._session_id:
                raise ValueError("Grok resume requires the stored session UUID")
            return [*cmd, "--resume", self._session_id]
        # Grok's initial positional prompt is delivered by its real TUI, not
        # typed into the terminal later, so this newly pinned transcript is
        # ready to tail as soon as it appears.
        return [*cmd, "--session-id", self._session_id, self.briefing()]

    @staticmethod
    def _assistant_text(record: dict) -> str | None:
        if record.get("type") != "assistant":
            return None
        content = record.get("content")
        if isinstance(content, str):
            return content if content.strip() else None
        if not isinstance(content, list):
            return None
        texts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ]
        body = "\n\n".join(text for text in texts if text.strip())
        return body if body.strip() else None

    async def _run(self):
        waited = 0.0
        path = self._transcript()
        while path is None and self.alive() and waited < self.TRANSCRIPT_TIMEOUT:
            await asyncio.sleep(self.POLL_SECONDS)
            waited += self.POLL_SECONDS
            path = self._transcript()
        if path is None:
            if self.alive():
                await self.post(
                    "system", "system",
                    f"@{self.att['name']}: no Grok transcript appeared after "
                    f"{int(self.TRANSCRIPT_TIMEOUT)}s; transcript tailing stopped",
                )
            return
        if self.on_cli_session is not None:
            self.on_cli_session(self._session_id)

        async def handle(record):
            body = self._assistant_text(record)
            if body is not None:
                await self.post(self.att["name"], "agent", body)

        # Grok records carry no timestamp, so a resume starts at the byte
        # cursor captured before respawn rather than using Adapter._fresh().
        # If statting before spawn failed, the base tailer seeks to end: replay
        # would be worse than missing only the interrupted turn.
        await self._tail_jsonl(
            str(path), handle, self._resume_offset if self.resume else 0,
        )
