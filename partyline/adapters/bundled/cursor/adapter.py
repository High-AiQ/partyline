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
    transcript_path,
)
from partyline.adapters.receipts import BEGAN, ENDED, receipt


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
            if st.st_mtime_ns != open_mtime_ns and st.st_size <= fh.tell():
                return True
            return False
        except OSError:
            return True

    async def _tail_transcript(self, path: Path) -> None:
        seen_fps: set[str] = set()
        if self.resume and path.is_file():
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if line.endswith("\n"):
                            seen_fps.add(fingerprint(line))
            except OSError:
                pass

        self.mark_ready()

        while self.alive():
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    open_mtime_ns = path.stat().st_mtime_ns
                    in_new_turn = False
                    while self.alive():
                        pos = fh.tell()
                        line = fh.readline()
                        if not line:
                            if self._is_replaced(fh, path, open_mtime_ns):
                                break
                            await asyncio.sleep(self.POLL_SECONDS)
                            continue
                        if not line.endswith("\n"):
                            if not self.alive():
                                return
                            fh.seek(pos)
                            await asyncio.sleep(0.3)
                            continue
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(record, dict):
                            continue
                        fp = fingerprint(line)
                        event, text = parse_record(record)
                        if event == ENDED:
                            if fp in seen_fps and not in_new_turn:
                                continue
                            seen_fps.add(fp)
                            in_new_turn = False
                            await receipt(self.att, event)
                            continue
                        if fp in seen_fps:
                            continue
                        seen_fps.add(fp)
                        if event == BEGAN or text:
                            in_new_turn = True
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
                        f"@{self.att['name']}: no Cursor session appeared after "
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
