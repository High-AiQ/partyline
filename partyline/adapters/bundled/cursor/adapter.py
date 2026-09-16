"""Interactive adapter for Cursor's `agent` CLI."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from pathlib import Path

from partyline.adapters import Adapter
from partyline.adapters.bundled.cursor.parse import (
    chat_dir,
    fingerprint,
    user_text,
    parse_record,
    resync_fingerprints,
    resync_positional,
    transcript_path,
)
from partyline.adapters.bundled.cursor.startup import (
    cursor_command,
    startup_diagnostics,
    terminate_process,
)
from partyline.adapters.bundled.cursor.wakes import WakeSettlement
from partyline.adapters.receipts import BEGAN, ENDED, receipt

logger = logging.getLogger(__name__)

class PartylineAdapter(WakeSettlement, Adapter):
    kind = "cursor"

    _CLAIMED: set[str] = set()
    _DISCOVERY = asyncio.Lock()
    INITIAL_DELAY = 3.0
    POLL_SECONDS = 0.5
    DISCOVERY_TIMEOUT = 45.0
    STARTUP_OUTPUT_LIMIT = 4096
    TERMINATE_GRACE = 0.5

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sentinel_fps: set[str] = set()
        self._failed_snapshot: tuple[str, ...] | None = None
        self._startup_output = bytearray()
        self._wakes_init()
    async def stop(self):
        self._CLAIMED.discard(getattr(self, "_session_id", "") or "")
        await super().stop()
    def build_command(self) -> list[str]:
        return cursor_command(
            list(self.att.get("command") or []), self.att["cwd"], self.resume,
            str(self.att.get("cli_session") or "").strip(),
        )
    def _find_chat(self) -> str | None:
        if self.resume and (session_id := self.att.get("cli_session")):
            sid = str(session_id).strip()
            return sid if sid not in self._CLAIMED else None
        chats = chat_dir(self.att["cwd"])
        if not chats.is_dir():
            return None
        candidates: list[tuple[float, str]] = []
        try:
            for item in chats.iterdir():
                if item.is_dir() and item.name not in self._CLAIMED:
                    try:
                        mtime = os.path.getmtime(item)
                        if mtime >= self.spawned_at - 2:
                            candidates.append((mtime, item.name))
                    except OSError:
                        continue
        except OSError:
            return None

        if candidates:
            candidates.sort(reverse=True)
            return candidates[0][1]
        return None

    async def on_output(self, data: bytes):
        remaining = self.STARTUP_OUTPUT_LIMIT - len(self._startup_output)
        if remaining > 0:
            self._startup_output.extend(data[:remaining])
    def _is_replaced(self, fh, path: Path, open_mtime_ns: int) -> bool:
        try:
            st = path.stat()
            if st.st_ino != os.fstat(fh.fileno()).st_ino or st.st_size < fh.tell():
                return True
            if st.st_mtime_ns != open_mtime_ns:
                return True
            return False
        except OSError:
            return True
    async def _handle_resync(
        self, path: Path, seen_fps: list[str], failures: int
    ) -> tuple[list[str], int]:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            return seen_fps, failures
        complete = [line for line in lines if line.endswith("\n")]
        incoming_fps = [fingerprint(line) for line in complete]
        for line, fp in zip(complete, incoming_fps, strict=True):
            if self._tail_is_turn_ended([line]):
                self._sentinel_fps.add(fp)
        resynced = resync_fingerprints(path, seen_fps, incoming_fps)
        if resynced == seen_fps and seen_fps:
            # An unchanged prefix is a successful sequential re-read, not a
            # failed re-anchor.  During Cursor's atomic rewrites this is the
            # usual case, so it must clear any earlier fruitless attempts.
            sequential = resync_positional(path, seen_fps, incoming_fps)
            if not self._has_complete_jsonl_tail(lines):
                return seen_fps, failures
            if sequential == seen_fps:
                self._failed_snapshot = None
                return seen_fps, 0
            if (
                incoming_fps[: len(seen_fps) - 1] == seen_fps[:-1]
                and seen_fps[-1] in self._sentinel_fps
            ):
                # Since 2026.08.25 Cursor deletes the trailing turn_ended
                # sentinel at the START of the next turn and appends the new
                # records in its place (a fresh sentinel lands at turn end);
                # older builds instead inserted the completed turn before the
                # still-present sentinel. Both shapes leave every delivered
                # non-sentinel record in place, so shrinking the watermark by
                # the already-seen sentinel lets the normal tail loop consume
                # whatever follows. A sentinel is never speech, so the shrink
                # cannot replay a delivered message. A rewrite that edits
                # earlier records deliberately falls through to the bounded
                # hatch.
                self._failed_snapshot = None
                return seen_fps[:-1], 0
            snapshot = tuple(incoming_fps)
            if snapshot != self._failed_snapshot:
                self._failed_snapshot = snapshot
                failures = 0
            failures += 1
            if failures >= 3:
                await self.post(
                    "system",
                    "system",
                    f"{self.att['name']}: transcript rewritten beyond recognition — "
                    "re-anchoring positionally",
                )
                self._failed_snapshot = None
                return resync_positional(path, seen_fps, incoming_fps), 0
            return seen_fps, failures
        self._failed_snapshot = None
        return resynced, 0
    @staticmethod
    def _has_complete_jsonl_tail(lines: list[str]) -> bool:
        """Whether a nonempty rewrite ends at a complete JSONL boundary."""
        return bool(lines) and lines[-1].endswith("\n")
    @staticmethod
    def _tail_is_turn_ended(lines: list[str]) -> bool:
        """Whether the complete tail record is Cursor's turn sentinel."""
        try:
            record = json.loads(lines[-1])
        except (IndexError, json.JSONDecodeError):
            return False
        return isinstance(record, dict) and record.get("type") == "turn_ended"
    async def _tail_transcript(self, path: Path) -> None:
        seen_fps: list[str] = []
        self._sentinel_fps = set()
        if self.resume and path.is_file():
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if line.endswith("\n"):
                            seen_fps.append(fingerprint(line))
                            if self._tail_is_turn_ended([line]):
                                self._sentinel_fps.add(seen_fps[-1])
            except OSError:
                pass

        self.mark_ready()
        resync_failures = 0

        while self.alive():
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    open_mtime_ns = path.stat().st_mtime_ns
                    matched = 0
                    while self.alive():
                        if self._is_replaced(fh, path, open_mtime_ns):
                            seen_fps, resync_failures = await self._handle_resync(
                                path, seen_fps, resync_failures
                            )
                            await asyncio.sleep(self.POLL_SECONDS)
                            break
                        pos = fh.tell()
                        line = fh.readline()
                        if not line:
                            await asyncio.sleep(self.POLL_SECONDS)
                            continue
                        if not line.endswith("\n"):
                            if not self.alive():
                                return
                            fh.seek(pos)
                            await asyncio.sleep(0.3)
                            continue
                        fp = fingerprint(line)
                        if matched < len(seen_fps):
                            if seen_fps[matched] == fp:
                                matched += 1
                                # Only the FULL watermark re-matching proves the
                                # file still follows delivered history. A partial
                                # prefix match before a mismatch is the rewrite
                                # cycle itself; resetting there kept the counter
                                # oscillating 0↔1 and made the escape hatch
                                # unreachable — the grok46 permanent mute.
                                if matched == len(seen_fps):
                                    resync_failures = 0
                                continue
                            seen_fps, resync_failures = await self._handle_resync(
                                path, seen_fps, resync_failures
                            )
                            await asyncio.sleep(self.POLL_SECONDS)
                            break
                        seen_fps.append(fp)
                        matched += 1
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(record, dict):
                            continue
                        if record.get("type") == "turn_ended":
                            self._sentinel_fps.add(fp)
                        event, text = parse_record(record)
                        if event == BEGAN:
                            await self._note_user_input(user_text(record))
                        elif event == ENDED:
                            self._note_turn_ended()
                        if event:
                            await receipt(self.att, event)
                        if text:
                            await self.post(self.att["name"], "agent", text)
            except OSError:
                if not self.alive():
                    return
                await asyncio.sleep(self.POLL_SECONDS)

    async def _run(self):
        await asyncio.sleep(self.INITIAL_DELAY)
        if not self.alive():
            return

        session_id = None
        lock = contextlib.nullcontext() if self.resume else self._DISCOVERY
        async with lock:
            if not self.resume:
                await self.send_keys(self.briefing())
            waited = 0.0
            while session_id is None and self.alive():
                session_id = self._find_chat()
                if session_id:
                    self._CLAIMED.add(session_id)
                    self._session_id = session_id
                    break
                await asyncio.sleep(self.POLL_SECONDS)
                waited += self.POLL_SECONDS
                if (11.9 <= waited <= 12.1 or 23.9 <= waited <= 24.1) and not self.resume:
                    await self.send_keys(self.briefing())
                elif waited > self.DISCOVERY_TIMEOUT:
                    diagnostic = startup_diagnostics(
                        getattr(self, "spawn_argv", self.build_command()),
                        self.att["cwd"], self._startup_output.decode(errors="replace"),
                    )
                    logger.warning("%s", diagnostic)
                    try:
                        await self.post(
                            "system",
                            "system",
                            f"{self.att['name']}: no Cursor session appeared after "
                            f"{int(self.DISCOVERY_TIMEOUT)}s — run `agent` manually once in "
                            f"{self.att['cwd']}, then re-attach. {diagnostic}",
                        )
                    finally:
                        await terminate_process(self.proc, self.TERMINATE_GRACE)
                    return

        if not session_id or not self.alive():
            return
        if self.on_cli_session:
            self.on_cli_session(session_id)

        path = transcript_path(self.att["cwd"], session_id)
        waited = 0.0
        while not path.is_file() and self.alive() and waited < self.DISCOVERY_TIMEOUT:
            await asyncio.sleep(self.POLL_SECONDS)
            waited += self.POLL_SECONDS
        if not path.is_file() or not self.alive():
            return

        await self._tail_transcript(path)
