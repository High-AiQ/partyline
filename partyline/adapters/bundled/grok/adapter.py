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
from partyline.adapters.bundled.grok.transcript import (
    assistant_count,
    assistant_scan,
    assistant_text,
    fingerprint,
    is_assistant_record,
)


class PartylineAdapter(Adapter):
    kind = "grok"
    # Kept as class attributes so a test can patch one on an instance, and so
    # the call sites below read the same as they did before the split.
    _assistant_text = staticmethod(assistant_text)
    _is_assistant_record = staticmethod(is_assistant_record)
    _fingerprint = staticmethod(fingerprint)
    _assistant_scan = staticmethod(assistant_scan)
    _assistant_count = staticmethod(assistant_count)
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
        # Fingerprints of every assistant record already accounted for, in
        # order. The ordinal alone cannot survive Grok rewriting the file with
        # a shorter history (compaction); the sequence can.
        self._assistant_fingerprints: list[bytes] = []
        # Set only once a pre-spawn count actually succeeds: that is the
        # lifecycle whose next replacement is a restore rather than a
        # compaction. Resuming alone does not imply it — with no transcript
        # before the spawn there is nothing to carry across, and a stale flag
        # would preserve an ordinal through a real compaction and mute the
        # process. The flag records what was observed, never what was assumed.
        self._resume_swap_pending = False

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
                scanned = self._assistant_scan(path)
                # An empty scan is never a true account of a resumed session:
                # a session with a history to resume has spoken at least once.
                # Accepting zero here is indistinguishable from "count later",
                # and it is the watermark that replays everything ever said.
                if scanned:
                    self._assistant_fingerprints = scanned
                    self._accounted = len(scanned)
                    self._resume_swap_pending = True
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
    def _identity(path: Path) -> tuple[int, int, int] | None:
        """What the file is right now, or ``None`` if it cannot be read."""
        try:
            status = path.stat()
        except OSError:
            return None
        return (status.st_ino, status.st_size, status.st_mtime_ns)

    async def _settled_assistant_scan(self, path: Path) -> list[bytes] | None:
        """Fingerprint a resumed transcript only once it has stopped changing.

        Grok recreates ``chat_history.jsonl`` when it resumes and fills the
        restored history back into it. Counting the instant the file appears
        can therefore catch it empty or half-written, and a watermark of zero
        relays everything the process ever said back into the room as if it
        were new — the failure this guard exists to make impossible.

        There is no signal from the CLI that the restore is finished, so the
        only honest one available is the file going quiet. If it never does,
        return ``None``: the caller refuses out loud rather than tailing from
        a count it cannot trust.

        Quiet before the scan is not enough. Reading the file takes time, and
        a restore that resumes mid-read yields a count of what the file used
        to hold — a short watermark, which is the same replay this guard
        exists to prevent, arriving through a narrower door. The scan is
        therefore bracketed: same inode, size, and mtime before and after, or
        the count is discarded and the stability window starts over.
        """
        previous = None
        stable_for = 0.0
        waited = 0.0
        while self.alive() and waited < self.SETTLE_TIMEOUT:
            current = self._identity(path)
            if current is None:
                return None
            if current == previous:
                stable_for += self.POLL_SECONDS
                if stable_for >= self.SETTLE_SECONDS:
                    scanned = self._assistant_scan(path)
                    if scanned is not None and self._identity(path) == current:
                        return scanned
                    previous, stable_for = None, 0.0
            else:
                previous, stable_for = current, 0.0
            await asyncio.sleep(self.POLL_SECONDS)
            waited += self.POLL_SECONDS
        return None

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
            scanned = await self._settled_assistant_scan(path)
            if scanned:
                self._assistant_fingerprints = scanned
                self._accounted = len(scanned)
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
                                await self._resync_after_replace(path)
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
                        # Genuine new speech proves the restore finished, so a
                        # later replacement really is a compaction.
                        self._resume_swap_pending = False
                        self._assistant_fingerprints.append(self._fingerprint(line))
                        await handle(record)
            except OSError:
                if not self.alive():
                    return
                await asyncio.sleep(self.POLL_SECONDS)

    async def _resync_after_replace(self, path: Path) -> None:
        """Re-anchor the replay watermark on the replacement file.

        Grok rewrites chat_history.jsonl when it compacts a session, dropping
        older records, so an ordinal counted against the previous file can
        exceed every index in the new one and mute all future replies. Align
        the records already seen with the start of the replacement — a
        compaction keeps the recent tail verbatim — and resume after the
        overlap. No overlap means nothing was retained, so every record in the
        replacement is genuinely new and must be relayed.

        The replacement is read only once it has stopped changing. Resuming a
        session replaces this file with an empty one and refills it, so a
        replacement read on arrival looks like a rewrite that retained
        nothing — the watermark drops to zero and the whole session is
        relayed to the room. That is the shape observed live on 2026-08-17,
        found by @sol: "no overlap" is only true of a *finished* file. If the
        replacement never settles, the previous watermark stands: relaying
        nothing is recoverable, relaying everything is not.
        """
        if self._resume_swap_pending:
            # The one replacement a resume performs. The replacement is a
            # superset of what was counted before the spawn, so the ordinal
            # carries across it unchanged; consulting overlap here is what
            # replayed whole sessions into the room, whether the file was
            # caught empty or caught halfway through its refill.
            self._resume_swap_pending = False
            return
        seen = self._assistant_fingerprints
        if not seen:
            # Nothing counted has a sequence to align; keep the ordinal.
            return
        incoming = await self._settled_assistant_scan(path)
        if not incoming:
            await self.post(
                "system", "system",
                f"@{self.att['name']}: the Grok transcript was replaced and has not "
                "settled; keeping the previous position rather than replaying history",
            )
            return
        low, high = 0, min(len(seen), len(incoming))
        while low < high:
            mid = (low + high + 1) // 2
            if seen[-mid:] == incoming[:mid]:
                low = mid
            else:
                high = mid - 1
        self._accounted = low

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
