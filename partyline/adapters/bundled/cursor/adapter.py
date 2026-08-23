"""Interactive adapter for Cursor's `agent` CLI."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from pathlib import Path

from partyline.adapters import Adapter
from partyline.adapters.bundled.cursor.parse import (
    chat_dir,
    fingerprint,
    parse_record,
    resync_fingerprints,
    resync_positional,
    transcript_path,
)
from partyline.adapters.receipts import BEGAN, receipt


class PartylineAdapter(Adapter):
    kind = "cursor"

    _CLAIMED: set[str] = set()
    _DISCOVERY = asyncio.Lock()
    INITIAL_DELAY = 3.0
    POLL_SECONDS = 0.5
    DISCOVERY_TIMEOUT = 45.0

    async def stop(self):
        self._CLAIMED.discard(getattr(self, "_session_id", "") or "")
        await super().stop()

    def build_command(self) -> list[str]:
        cmd = list(self.att.get("command") or []) or ["agent", "--yolo", "--trust"]
        if self.resume:
            session_id = str(self.att.get("cli_session") or "").strip()
            if session_id and "--resume" not in cmd and "-r" not in cmd:
                cmd = [*cmd, "--resume", session_id]
        return cmd

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
        incoming_fps = [fingerprint(line) for line in lines if line.endswith("\n")]
        resynced = resync_fingerprints(path, seen_fps, incoming_fps)
        if resynced == seen_fps and seen_fps:
            # An unchanged prefix is a successful sequential re-read, not a
            # failed re-anchor.  During Cursor's atomic rewrites this is the
            # usual case, so it must clear any earlier fruitless attempts.
            sequential = resync_positional(path, seen_fps, incoming_fps)
            if not self._has_complete_jsonl_tail(lines):
                return seen_fps, failures
            if sequential == seen_fps:
                return seen_fps, 0
            if (
                incoming_fps[: len(seen_fps) - 1] == seen_fps[:-1]
                and incoming_fps[-1:] == seen_fps[-1:]
                and self._tail_is_turn_ended(lines)
            ):
                # Current Cursor inserts one completed turn before the single
                # trailing sentinel when it re-renders the file. Shrinking the
                # watermark by that sentinel lets the normal tail loop consume
                # the inserted records without replaying delivered speech.
                # A rewrite spanning multiple prior turns may not have this
                # shape and deliberately falls through to the bounded hatch.
                return seen_fps[:-1], 0
            failures += 1
            if failures >= 3:
                await self.post(
                    "system",
                    "system",
                    f"{self.att['name']}: transcript rewritten beyond recognition — "
                    "re-anchoring positionally",
                )
                return resync_positional(path, seen_fps, incoming_fps), 0
            return seen_fps, failures
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

    async def deliver(self, messages: list[dict]):
        """Arm presence when input reaches a CLI that writes only at turn end."""
        text = self.format_digest(messages)
        await super().deliver(messages)
        if text.strip():
            await receipt(self.att, BEGAN)

    async def _tail_transcript(self, path: Path) -> None:
        seen_fps: list[str] = []
        if self.resume and path.is_file():
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if line.endswith("\n"):
                            seen_fps.append(fingerprint(line))
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
                        event, text = parse_record(record)
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
                    await self.post(
                        "system",
                        "system",
                        f"{self.att['name']}: no Cursor session appeared after "
                        f"{int(self.DISCOVERY_TIMEOUT)}s — run `agent` manually once in "
                        f"{self.att['cwd']}, then re-attach.",
                    )
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
