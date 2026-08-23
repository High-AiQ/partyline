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
from partyline.adapters.bundled.grok.resume import (
    align_delivery_history,
    file_identity,
    settled_scan,
)
from partyline.adapters.bundled.grok.tail import (
    resync_after_replace,
    tail_grok_transcript,
)
from partyline.adapters.bundled.grok.transcript import (
    assistant_count,
    assistant_records,
    assistant_scan,
    assistant_text,
    fingerprint,
    is_assistant_record,
    latest_user_prompt,
)
from partyline.adapters.bundled.grok.wake_receipts import WakeReceipts
from partyline.adapters.bundled.grok import turn_hooks


class PartylineAdapter(Adapter):
    kind = "grok"
    # Kept as class attributes so a test can patch one on an instance, and so
    # the call sites below read the same as they did before the split.
    _assistant_text = staticmethod(assistant_text)
    _is_assistant_record = staticmethod(is_assistant_record)
    _fingerprint = staticmethod(fingerprint)
    _assistant_scan = staticmethod(assistant_scan)
    _assistant_records = staticmethod(assistant_records)
    _assistant_count = staticmethod(assistant_count)
    _identity = staticmethod(file_identity)
    POLL_SECONDS = 0.5
    TRANSCRIPT_TIMEOUT = 45.0
    # How long a resumed transcript must stop changing before it is counted,
    # and how long to wait for that to happen.
    SETTLE_SECONDS = 1.0
    SETTLE_TIMEOUT = 30.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Attachment ids are server-generated UUIDs. Passing one straight to
        # Grok pins a fresh session to this attachment, without another source
        # of identity that could diverge from the stored attachment record.
        stored_session = str(self.att.get("cli_session") or "").strip()
        self._session_id = stored_session if self.resume else self.att["id"]
        self._accounted: int | None = None if self.resume else 0
        history = self.att.get("delivered_bodies")
        self._delivered_bodies = list(history) if history is not None else None
        self._delivered_transcript_records = list(
            self.att.get("delivered_transcript_records") or []
        )
        self._legacy_relayed_bodies = list(self.att.get("legacy_relayed_bodies") or [])
        self._mark_transcript_delivery = self.att.get("mark_transcript_delivery")
        self._post_resume_record = self.att.get("post_resume_record")
        self._backlog_to_record = 0
        self._delivery_skip: set[int] = set()
        self._pending_backlog = 0
        self._delivery_plan = None
        # Fingerprints of accounted records, in order: an ordinal alone
        # cannot survive Grok rewriting the file shorter; the sequence can.
        self._assistant_fingerprints: list[bytes] = []
        # Set only once a pre-spawn count succeeds: that is the lifecycle
        # whose next replacement is a restore, not a compaction. Resuming
        # alone does not imply it, and a stale flag would carry an ordinal
        # through a real compaction and mute the process. The flag records
        # what was observed, never what was assumed.
        self._resume_swap_pending = False
        self._restoring_to: int | None = None  # refill target to count restored
        self._refused_resync = False  # told the room about a refused re-anchor?
        self._wake_receipts = WakeReceipts()

    def _transcript(self) -> Path | None:
        """Return the one transcript whose caller-pinned UUID matches."""
        pattern = os.path.expanduser(
            f"~/.grok/sessions/*/{self._session_id}/chat_history.jsonl"
        )
        paths = [Path(path) for path in glob.glob(pattern)]
        return paths[0] if len(paths) == 1 else None

    async def start(self):
        if self.resume and self._delivered_bodies is None:
            if not self._session_id:
                raise ValueError("Grok resume requires the stored session UUID")
            path = self._transcript()
            if path is not None:
                scanned = self._assistant_scan(path)
                # An empty scan is never a true account of a resumed session:
                # a session with a history to resume has spoken at least once.
                # Accepting zero here is indistinguishable from "count later",
                # and it is the watermark that replays everything ever said.
                if scanned:
                    self._assistant_fingerprints = scanned
                    self._accounted = len(scanned)
                    self._resume_swap_pending = True
        if self.att.get("hook_url"):
            turn_hooks.install(str(self.att["hook_url"]), self._session_id, self.att)
        try:
            await super().start()
        except Exception:
            turn_hooks.uninstall(self._session_id, self.att)
            raise

    async def stop(self):
        turn_hooks.uninstall(self._session_id, self.att)
        self._wake_receipts.stop()
        await super().stop()

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

    async def _settled_assistant_scan(self, path: Path) -> list[bytes] | None:
        return await settled_scan(self, path, self._assistant_scan)

    async def _align_delivery_history(self, path: Path) -> bool:
        return await align_delivery_history(self, path)

    async def deliver(self, messages: list[dict]):
        """Paste now, but let a newer structured user record credit the ids."""
        if self.att.get("confirm_delivery_ids") is None:
            return await super().deliver(messages)
        return await self._wake_receipts.deliver(self, messages)

    async def _note_user_record(self, record: object) -> None:
        await self._wake_receipts.observe(self, record)

    async def wait_delivery_received(self, message_ids: list[int]) -> bool:
        return await self._wake_receipts.wait(message_ids)

    def prepare_delivery_receipt(self, message_ids: list[int]) -> None:
        self._wake_receipts.expect_wait(message_ids)

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
                    f"{self.att['name']}: no Grok transcript appeared after "
                    f"{int(self.TRANSCRIPT_TIMEOUT)}s; transcript tailing stopped",
                )
            return
        if self.on_cli_session is not None:
            self.on_cli_session(self._session_id)

        if self.resume and self._delivered_bodies is not None:
            await self._align_delivery_history(path)
        elif self.resume and self._accounted is None:
            # Do not mistake an unavailable pre-spawn count for an empty
            # history: zero would replay every old reply after resume.
            scanned = await self._settled_assistant_scan(path)
            if scanned:
                self._assistant_fingerprints = scanned
                self._accounted = len(scanned)
        if self._accounted is None:
            await self.post(
                "system", "system",
                f"{self.att['name']}: Grok transcript history could not be counted; "
                "reply tailing stopped to avoid replaying prior speech",
            )
            self._mark_not_ready()
            return
        self._wake_receipts.seed(latest_user_prompt(path))

        async def handle(record):
            body = self._assistant_text(record)
            if body is not None:
                await self.post(self.att["name"], "agent", body)

        await self._tail_grok_transcript(path, handle)

    async def _poll(self) -> None:
        """The only wait the transcript tail is allowed to take.

        Tests that need the tail to stop patch this method. Patching
        ``adapter.asyncio.sleep`` after the loop moves to ``tail.py`` does
        nothing, and the poll never yields.
        """
        await asyncio.sleep(self.POLL_SECONDS)

    async def _tail_grok_transcript(self, path: Path, handle) -> None:
        await tail_grok_transcript(self, path, handle)

    async def _resync_after_replace(self, path: Path) -> None:
        await resync_after_replace(self, path)

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
