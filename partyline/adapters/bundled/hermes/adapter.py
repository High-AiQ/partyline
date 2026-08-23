"""Adapter for the Hermes interactive terminal application.

Hermes stores its canonical transcript in ``state.db``.  The CLI generates
its own session id, so a fresh process is associated with the row created just
after its PTY starts.  Discovery is serialized and each row is claimed before
it can be tailed by another attachment.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import threading
import time
from pathlib import Path
from urllib.parse import quote

from partyline.adapters import Adapter


class PartylineAdapter(Adapter):
    kind = "hermes"

    _claims_lock = threading.Lock()
    _claimed_sessions: set[str] = set()
    DISCOVERY_LOOKBACK = 5.0
    DISCOVERY_TIMEOUT = 90.0
    POLL_SECONDS = 0.5

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._session_id: str | None = None
        self._db: sqlite3.Connection | None = None

    @staticmethod
    def _db_path() -> Path:
        home = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
        return home / "state.db"

    @classmethod
    def _release(cls, session_id: str | None):
        if session_id is None:
            return
        with cls._claims_lock:
            cls._claimed_sessions.discard(session_id)

    def _open_db(self) -> sqlite3.Connection | None:
        path = self._db_path()
        if not path.is_file():
            return None
        # URI mode=ro is deliberate: the adapter must never create or mutate
        # the user's session store, including its journal files.
        uri = f"file:{quote(str(path), safe='/')}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=0.5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        return conn

    def build_command(self) -> list[str]:
        cmd = list(self.att["command"]) or list(self.att["adapter_metadata"]["command"])
        if "--cli" not in cmd and "--tui" not in cmd:
            cmd.append("--cli")
        if "--pass-session-id" not in cmd:
            cmd.append("--pass-session-id")
        if self.resume:
            session_id = str(self.att.get("cli_session") or "").strip()
            if not session_id:
                raise ValueError("hermes resume requires the stored session id")
            if "--resume" not in cmd and "-r" not in cmd:
                cmd.extend(["--resume", session_id])
        return cmd

    def _same_cwd(self, value: str | None) -> bool:
        if not value:
            return False
        try:
            return os.path.realpath(value) == os.path.realpath(self.att["cwd"])
        except (OSError, TypeError):
            return value == self.att["cwd"]

    def _discover(self) -> str | None:
        if self._db is None:
            return None
        start = self.spawned_at - self.DISCOVERY_LOOKBACK
        now = time.time()
        with self._claims_lock:
            rows = self._db.execute(
                "SELECT id, cwd FROM sessions "
                "WHERE started_at >= ? AND started_at <= ? "
                "ORDER BY started_at ASC, id ASC",
                (start, now),
            ).fetchall()
            candidates = [row for row in rows if self._same_cwd(row["cwd"])]
            for row in candidates:
                session_id = str(row["id"])
                if session_id not in self._claimed_sessions:
                    self._claimed_sessions.add(session_id)
                    return session_id
        return None

    def _latest_message_id(self, session_id: str) -> int:
        assert self._db is not None
        row = self._db.execute(
            "SELECT COALESCE(MAX(id), 0) AS id FROM messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return int(row["id"] if row else 0)

    def _compression_child(self, session_id: str) -> str | None:
        assert self._db is not None
        row = self._db.execute(
            "SELECT id FROM sessions WHERE parent_session_id = ? "
            "ORDER BY started_at DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        return str(row["id"]) if row else None

    @staticmethod
    def _text(content) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n\n".join(
                str(item.get("text", ""))
                for item in content
                if isinstance(item, dict) and item.get("text")
            )
        if isinstance(content, dict):
            return str(content.get("text") or content.get("content") or "")
        return "" if content is None else str(content)

    @classmethod
    def _assistant_text(cls, row) -> str | None:
        """Relay live assistant speech, never a compacted lineage snapshot."""
        if row["role"] != "assistant" or row["compacted"]:
            return None
        if str(row["display_kind"] or "").startswith("compression"):
            return None
        body = cls._text(row["content"]).strip()
        return body or None

    async def _tail(self, session_id: str, last_id: int):
        assert self._db is not None
        while self.alive():
            if child := self._compression_child(session_id):
                self._release(session_id)
                with self._claims_lock:
                    self._claimed_sessions.add(child)
                session_id = child
                self._session_id = child
                # The child starts as a rewritten compacted snapshot. Snapshot
                # it as seen so retained assistant history cannot replay.
                last_id = self._latest_message_id(child)
                if self.on_cli_session is not None:
                    self.on_cli_session(child)
            rows = self._db.execute(
                "SELECT id, role, content, compacted, display_kind FROM messages "
                "WHERE session_id = ? AND id > ? AND active = 1 ORDER BY id",
                (session_id, last_id),
            ).fetchall()
            for row in rows:
                last_id = max(last_id, int(row["id"]))
                if body := self._assistant_text(row):
                    await self.post(self.att["name"], "agent", body)
            await asyncio.sleep(self.POLL_SECONDS)

    async def _run(self):
        try:
            # Hermes renders a fairly large startup screen before its input
            # reader is ready.  Sending the paste earlier can leave the text
            # visible but drop the terminating Enter.
            waited = 0.0
            while self.alive() and waited < 30.0:
                if "Welcome to Hermes Agent" in self.screen_text():
                    break
                await asyncio.sleep(0.5)
                waited += 0.5
            if not self.alive():
                return

            self._db = self._open_db()
            if self._db is None:
                await self.post(
                    "system", "system",
                    f"{self.att['name']} could not open the Hermes session store read-only",
                )
                return

            if self.resume:
                self._session_id = str(self.att.get("cli_session") or "").strip() or None
                if self._session_id is None:
                    return
                last_id = self._latest_message_id(self._session_id)
            else:
                await self.send_keys(self.briefing())
                # A slow paste can still race prompt_toolkit's input reader;
                # a second Enter is harmless if the first one was accepted.
                await asyncio.sleep(1.0)
                if self.alive():
                    self.send_key("enter")
                waited = 0.0
                while self.alive() and waited < self.DISCOVERY_TIMEOUT:
                    self._session_id = self._discover()
                    if self._session_id is not None:
                        break
                    await asyncio.sleep(1.0)
                    waited += 1.0
                if self._session_id is None:
                    await self.post(
                        "system", "system",
                        f"{self.att['name']}: no Hermes session appeared after "
                        f"{int(self.DISCOVERY_TIMEOUT)}s; transcript tailing stopped",
                    )
                    return
                if self.on_cli_session is not None:
                    self.on_cli_session(self._session_id)
                last_id = self._latest_message_id(self._session_id)

            # Both resume and fresh paths have an unambiguous session and a
            # cursor before the tail begins, which is the safe sequencing point.
            self.mark_ready()
            await self._tail(self._session_id, last_id)
        finally:
            self._release(self._session_id)
            if self._db is not None:
                self._db.close()
                self._db = None
