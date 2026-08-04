"""Transcript adapter for the OpenCode interactive terminal application.

OpenCode records sessions in its local SQLite store.  The terminal remains the
input channel, while only completed assistant text parts are relayed to chat.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sqlite3
from pathlib import Path

from partyline.adapters import Adapter


STORE = Path.home() / ".local" / "share" / "opencode" / "opencode.db"


class PartylineAdapter(Adapter):
    kind = "opencode"

    # A session created by a fresh TUI has no caller-supplied identifier.  Do
    # discovery one at a time and claim the result so concurrent attachments in
    # one directory never tail the same transcript.
    _CLAIMED: set[str] = set()
    _DISCOVERY = asyncio.Lock()

    async def stop(self):
        self._CLAIMED.discard(getattr(self, "_session_id", "") or "")
        await super().stop()

    def build_command(self) -> list[str]:
        cmd = list(self.att["command"]) or ["opencode"]
        if self.resume and self.att.get("cli_session") and "--session" not in cmd and "-s" not in cmd:
            cmd += ["--session", self.att["cli_session"]]
        return cmd

    @staticmethod
    def _connect() -> sqlite3.Connection:
        # This is deliberately a short-lived, read-only connection: the store
        # belongs to the interactive application and is commonly in WAL mode.
        return sqlite3.connect(f"{STORE.as_uri()}?mode=ro", uri=True)

    def _find_session(self) -> str | None:
        if self.resume and (session_id := self.att.get("cli_session")):
            return str(session_id) if session_id not in self._CLAIMED else None
        if not STORE.exists():
            return None
        cutoff = int((self.spawned_at - 2) * 1000)
        try:
            with self._connect() as db:
                rows = db.execute(
                    "SELECT id FROM session WHERE directory = ? AND time_created >= ? "
                    "ORDER BY time_created DESC",
                    (self.att["cwd"], cutoff),
                ).fetchall()
        except sqlite3.Error:
            return None
        for (session_id,) in rows:
            if session_id not in self._CLAIMED:
                return str(session_id)
        return None

    async def _run(self):
        await asyncio.sleep(3.0)
        if not self.alive():
            return

        session_id = None
        lock = contextlib.nullcontext() if self.resume else self._DISCOVERY
        async with lock:
            if not self.resume:
                await self.send_keys(self.briefing())
            waited = 0.0
            while session_id is None and self.alive():
                session_id = self._find_session()
                if session_id:
                    self._CLAIMED.add(session_id)
                    self._session_id = session_id
                    break
                await asyncio.sleep(1.0)
                waited += 1.0
                if waited > 45.0:
                    await self.post(
                        "system", "system",
                        f"@{self.att['name']}: no session appeared after 45s — run the CLI "
                        f"once in {self.att['cwd']}, then re-attach.",
                    )
                    return
        if not session_id:
            return
        if self.on_cli_session:
            self.on_cli_session(session_id)

        # Do not repeat old parts when reconnecting to an existing session.
        started_ms = int((self.spawned_at - 1) * 1000)
        seen: set[str] = set()
        while self.alive():
            try:
                with self._connect() as db:
                    rows = db.execute(
                        "SELECT part.id, part.data FROM part "
                        "JOIN message ON message.id = part.message_id "
                        "WHERE part.session_id = ? AND part.time_created >= ? "
                        "AND json_extract(message.data, '$.role') = 'assistant' "
                        "AND json_extract(part.data, '$.type') = 'text' "
                        "ORDER BY part.time_created, part.id",
                        (session_id, started_ms),
                    ).fetchall()
            except sqlite3.Error:
                await asyncio.sleep(0.5)
                continue
            for part_id, raw_data in rows:
                if part_id in seen:
                    continue
                seen.add(part_id)
                try:
                    body = json.loads(raw_data).get("text", "")
                except (TypeError, json.JSONDecodeError):
                    continue
                if isinstance(body, str) and body.strip():
                    await self.post(self.att["name"], "agent", body)
            await asyncio.sleep(0.5)
