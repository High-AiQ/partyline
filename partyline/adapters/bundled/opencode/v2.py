"""OpenCode 2 session_message transcripts; all input stays in the real TUI.

Schema: anomalyco/opencode v2, packages/schema/src/session-message.ts and
packages/core/src/session/sql.ts. Idle records close turns, including aborts;
assistant completion alone can precede another tool step.
"""

import asyncio
import logging
import os
from pathlib import Path
import sqlite3
import subprocess
import threading
import time

from partyline.adapters import Adapter
from partyline.adapters.bundled.opencode.command import Command
from partyline.adapters.bundled.opencode.provider_log import ProviderLog
from partyline.adapters.bundled.opencode.store import SessionStore
from partyline.adapters.bundled.opencode.wakes import WakeSettlement
from partyline.adapters.compaction import is_compaction_record
from partyline.adapters.receipts import BEGAN, ENDED, receipt

logger = logging.getLogger(__name__)
RESUME_READY_TIMEOUT_SECONDS = 30.0
RECHECK_SECONDS = 0.05


class PartylineAdapter(Command, SessionStore, WakeSettlement, Adapter):
    kind = "opencode-v2"
    _CLAIMED: dict[tuple[str, str], str] = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._wakes_init()
        self._store: Path | None = None
        self._session_id: str | None = None
        self._claim_seq = 0
        self._seen: set[str] = set()
        self.provider_failed = False
        self._provider_log = None
        self._busy = False
        self.last_transcript_progress = time.monotonic()
        self._row_versions: dict[str, int] = {}
        self._resume_claimed_at: float | None = None
        # Wakes that were terminal output or exit; the notification count last acted on;
        # and the one later look owed after a notification that showed nothing new.
        self._other_wakes = 0
        self._read_at: int | None = None
        self._recheck_at: float | None = None
        self._store_lock = threading.Lock()

    async def start(self):
        path = await asyncio.to_thread(self._resolve_path, "log")
        self._provider_log = await asyncio.to_thread(self._open_provider_log, path)
        await super().start()

    def _open_provider_log(self, path):
        return ProviderLog(path if path.suffix == ".log" else path / "opencode.log",
                           self._claim_token, self.att["cwd"])

    def _resolve_store(self) -> Path:
        return self._resolve_path("db")

    def _resolve_path(self, kind) -> Path:
        # This diagnostic prints a path only: no server, session, or model call.
        executable = (self.att["command"] or ["opencode2"])[0]
        result = subprocess.run(
            [executable, "debug", "paths", kind], check=True, capture_output=True,
            text=True, timeout=15, cwd=self.att["cwd"],
            env=dict(os.environ, **self.spawn_env()),
        )
        path = Path(result.stdout.strip())
        if not path.is_absolute():
            raise ValueError("OpenCode v2 must use an absolute, on-disk diagnostic path")
        return path

    def _find_session(self) -> str | None:
        """Only a user row containing this activation's nonce can claim a session."""
        with self._reading() as db:
            rows = db.execute(
                "SELECT s.id, m.seq, m.data FROM session_v2 s "
                "JOIN session_message m ON m.session_id = s.id "
                "WHERE s.directory = ? AND s.parent_id IS NULL AND m.type = 'user' "
                "AND m.time_created >= ? AND instr(m.data, ?) > 0",
                (self.att["cwd"].replace("\\", "/"), int(self.spawned_at * 1000),
                 self._claim_token),
            ).fetchall()
        for session, seq, raw in rows:
            if self.resume and session != self.att.get("cli_session"):
                continue
            if (str(self._store), session) in self._CLAIMED:
                continue
            data = self._decode(raw)
            if isinstance(data.get("text"), str) and self._claim_token in data["text"]:
                self._claim_seq = seq
                self.observe_claim(data["text"])
                self._resume_claimed_at = time.monotonic()
                return session
        return None

    async def _poll_provider(self):
        if self._provider_log is None:
            return
        errors = await asyncio.to_thread(self._provider_log.poll)
        if not errors:
            return
        self.provider_failed = True
        self._busy = False
        for cause, fresh in errors:
            if noted := self.att.get("on_provider_error"):
                await noted(cause, fresh)
            elif fresh:
                await self.post("system", "system",
                                f"⚠ @{self.att['name']}: model provider error — {cause}")
        await receipt(self.att, ENDED)

    async def _poll(self) -> bool:
        """Settle what is new; False when nothing was committed since the last read."""
        rows = await asyncio.to_thread(self._unsettled_rows)
        for ident, kind, raw in rows or ():
            version = hash((kind, raw))
            if self._row_versions.get(ident) != version:
                self._row_versions[ident] = version
                self.last_transcript_progress = time.monotonic()
            if ident in self._seen:
                continue
            data = self._decode(raw)
            if not data:
                continue
            if kind == "compaction":
                # The row type is the shape; only completed ones count. The
                # seen-set is the dedup: a re-read row never counts twice.
                # A row first seen while the compaction runs is read again until it is
                # complete: settled on first sight, it was never counted.
                if not is_compaction_record("opencode-v2", {**data, "type": kind}):
                    continue
                noted = self.att.get("on_compaction")
                if noted:
                    await noted(data.get("reason") or "auto")
                self._seen.add(ident)
                self._row_versions.pop(ident, None)
                continue
            if kind == "assistant":
                timing = data.get("time")
                if not isinstance(timing, dict) or timing.get("completed") is None:
                    continue
                content = data.get("content", [])
                if isinstance(content, list):
                    for part in content:
                        if not isinstance(part, dict) or part.get("type") != "text":
                            continue
                        text = part.get("text")
                        if isinstance(text, str) and text.strip():
                            self.provider_failed = False
                            await self.post(self.att["name"], "agent", text)
            elif kind == "user":
                self.observe_claim(raw)
                await self._observe_user_part(raw, part_id=ident)
                if not self._busy:
                    self._busy = True
                    await receipt(self.att, BEGAN)
                if not self.resume:
                    self.mark_ready()
            elif kind == "synthetic":
                # A background job or subagent finishing prompts the model with no user
                # row. Without this the process read as idle while it worked, and its
                # turn never ended for the return path. An unfinished assistant row is
                # not the signal: an aborted step leaves one behind after its idle.
                if not self._busy:
                    self._busy = True
                    await receipt(self.att, BEGAN)
            elif kind == "idle":
                if self._busy:
                    self._busy = False
                    await receipt(self.att, ENDED)
                # A resume claim starts a real model turn. The TUI can drop
                # input during that turn; open delivery only at its idle receipt.
                self.mark_ready()
                self._schedule_unproved_repool()
            self._seen.add(ident)
            self._row_versions.pop(ident, None)
        self._after_poll()
        return rows is not None

    def _after_poll(self):
        # Readiness must not strand sequential recovery if the provider hangs
        # or errors without an idle row. This opens no delivery credit or idle.
        if (self.resume and self._resume_claimed_at is not None
                and time.monotonic() - self._resume_claimed_at >= RESUME_READY_TIMEOUT_SECONDS):
            self.mark_ready()
        # An idle TUI may discard a paste without producing another record.
        # Revisit unproved input even when there is no new idle row to tail.
        if not self._busy:
            self._schedule_unproved_repool()

    async def _run(self):
        try:
            await self._tail_session()
        except Exception as exc:
            self._mark_not_ready()
            logger.exception("OpenCode v2 transcript watcher failed")
            try:
                await self.post("system", "system", f"{self.att['name']}: OpenCode v2 "
                                f"transcript startup or monitoring failed: {exc}. "
                                "Stopping this process; unread messages remain pending.")
            finally:
                from ....attachment_stop_audit import direct_stop
                direct_stop(self.att["id"], "opencode.transcript_watcher_failure")
                await self.stop()
        finally:
            # A watcher that ends must never leave a readiness waiter stranded.
            self._mark_not_ready()
            self._release_claim()
            self._close_store()

    async def _tail_session(self):
        self._store = await asyncio.to_thread(self._resolve_store)
        self._store_open = True
        paths = [self._store]
        if self._provider_log is not None:
            paths.append(self._provider_log.path)
        async with self.file_events(*paths, changes=self._changes):
            await self._follow_session()

    async def _follow_session(self):
        deadline = self.event_time() + 45.0
        submitted = False
        while self.event_time() < deadline:
            if not self.alive():
                return
            try:
                self._session_id = self._find_session()
            except sqlite3.Error:
                pass
            if self._session_id:
                self._CLAIMED[(str(self._store), self._session_id)] = self._claim_token
                if self.on_cli_session:
                    self.on_cli_session(self._session_id)
                break
            await self._poll_provider()
            # 2.0.18 can leave --prompt in the composer without submitting it.
            # Only press Enter once it is visibly loaded; readiness and speech
            # still require the nonce in a structured user row, never the screen.
            if not submitted and self._claim_token in self.screen_text():
                await self._write_all(b"\r")
                submitted = True
            await self.wait_for_change(max(0, deadline - self.event_time()))
        else:
            raise RuntimeError("no claimed OpenCode v2 session appeared after 45s; "
                               "check the terminal for startup errors")
        while self.alive():
            stored = self._changes.version - self._other_wakes
            due = self._recheck_at is not None and self.event_time() >= self._recheck_at
            if stored == self._read_at and not due:
                self._after_poll()  # a deadline or terminal output: nothing new to read
            else:
                try:
                    await self._poll()
                    # A notification can arrive before the commit it announces is visible,
                    # and a read that found one commit can still be short of the next.
                    # no-poll (b): one later look per notification; that look arms nothing
                    self._recheck_at = (self.event_time() + RECHECK_SECONDS
                                        if stored != self._read_at else None)
                    self._read_at = stored
                except sqlite3.Error as exc:
                    self._recheck_at = None  # a failing store is retried on the next wake only
                    logger.debug("OpenCode v2 poll skipped: %s", exc)
                await self._poll_provider()
            delay = None
            if self.resume and not self._ready.is_set() and self._resume_claimed_at is not None:
                delay = max(0, self._resume_claimed_at + RESUME_READY_TIMEOUT_SECONDS - time.monotonic())
            if self._recheck_at is not None:
                remaining = max(0, self._recheck_at - self.event_time())
                delay = remaining if delay is None else min(delay, remaining)
            await self.wait_for_change(delay)

    def _release_claim(self):
        key = (str(self._store), self._session_id)
        if self._CLAIMED.get(key) == self._claim_token:
            del self._CLAIMED[key]

    async def stop(self):
        try:
            await super().stop()
        finally:
            self._release_claim()
