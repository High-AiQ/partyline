"""Adapter for Grok Build's interactive terminal.

Grok accepts a caller-generated UUID for a fresh interactive session. Its
JSONL transcript therefore has an exact, attachment-owned location rather
than needing unsafe discovery by working directory or modification time.
"""

from __future__ import annotations

import asyncio
import glob
import json
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
        self._accounted: int | None = None if self.resume else 0

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
                self._accounted = self._assistant_count(path)
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
    def _assistant_text(record: object) -> str | None:
        if not isinstance(record, dict):
            return None
        if record.get("type") != "assistant":
            return None
        # Grok's observed tool-using records keep their user-facing content
        # as a string and put calls in this sibling array. That content is
        # progress narration, not a completed reply for the room.
        if record.get("tool_calls"):
            return None
        content = record.get("content")
        if isinstance(content, str):
            return content if content.strip() else None
        if not isinstance(content, list):
            return None
        # No captured Grok transcript has used blocks; support them only as a
        # defensive compatibility shape, not as an asserted vendor contract.
        texts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ]
        body = "\n\n".join(text for text in texts if text.strip())
        return body if body.strip() else None

    @staticmethod
    def _is_assistant_record(record: object) -> bool:
        return isinstance(record, dict) and record.get("type") == "assistant"

    @classmethod
    def _assistant_count(cls, path: Path) -> int | None:
        """Count committed assistant records without trusting byte offsets."""
        count = 0
        try:
            with path.open(encoding="utf-8", errors="replace") as file:
                for line in file:
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    count += cls._is_assistant_record(record)
        except OSError:
            return None
        return count

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

        if self.resume and self._accounted is None:
            # Do not mistake an unavailable pre-spawn count for an empty
            # history: zero would replay every old reply after resume.
            self._accounted = self._assistant_count(path)
        if self._accounted is None:
            await self.post(
                "system", "system",
                f"@{self.att['name']}: Grok transcript history could not be counted; "
                "reply tailing stopped to avoid replaying prior speech",
            )
            self._mark_not_ready()
            return

        async def handle(record):
            body = self._assistant_text(record)
            if body is not None:
                await self.post(self.att["name"], "agent", body)

        await self._tail_grok_transcript(path, handle)

    async def _tail_grok_transcript(self, path: Path, handle) -> None:
        """Tail Grok's transcript across its atomic resume-time replacement."""
        assert self._accounted is not None
        while self.alive():
            try:
                with path.open(encoding="utf-8", errors="replace") as file:
                    assistant_index = 0
                    self.mark_ready()
                    while self.alive():
                        position = file.tell()
                        line = file.readline()
                        if not line:
                            if self._replaced(file, path):
                                break
                            await asyncio.sleep(self.POLL_SECONDS)
                            continue
                        if not line.endswith("\n"):
                            file.seek(position)
                            await asyncio.sleep(self.POLL_SECONDS)
                            continue
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if not self._is_assistant_record(record):
                            continue
                        assistant_index += 1
                        if assistant_index <= self._accounted:
                            continue
                        self._accounted += 1
                        await handle(record)
            except OSError:
                if not self.alive():
                    return
                await asyncio.sleep(self.POLL_SECONDS)

    @staticmethod
    def _replaced(file, path: Path) -> bool:
        """Whether a held transcript handle no longer names the live file."""
        try:
            current = path.stat()
            return (
                current.st_ino != os.fstat(file.fileno()).st_ino
                or current.st_size < file.tell()
            )
        except OSError:
            return True
