"""Transcript adapter for the OpenCode interactive terminal application.

OpenCode records sessions in its local SQLite store.  The terminal remains the
input channel, while only completed assistant text parts are relayed to chat.

The same store carries this harness's turn boundaries, which presence needs
to clear the working badge: a user message appears when the CLI actually
reads a pasted digest (turn began), and an agentic loop is over when an
assistant message completes with any finish reason but ``tool-calls`` (turn
ended). Both are reported as receipts. A turn aborted with Esc writes no
completing row, so its end is reported when a later row supersedes the
un-completed one — the only deterministic death signal the store offers,
and without it one aborted turn wedges the badge for every clean turn after
it (the open count never returns to zero).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sqlite3
import time
from pathlib import Path

from partyline.adapters.events import watch_files

from partyline.adapters import Adapter
from partyline.adapters.receipts import BEGAN, ENDED, receipt
from partyline.adapters.store_wake import StoreWake
from partyline.adapters.bundled.opencode.wakes import WakeSettlement
from partyline.adapters.bundled.opencode.boundary import boundary_event

logger = logging.getLogger(__name__)


STORE = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
RESUME_PROBE_INTERVAL = 5.0


class PartylineAdapter(WakeSettlement, Adapter):
    kind = "opencode"

    # Serialize discovery so concurrent attachments claim separate transcripts.
    _CLAIMED: set[str] = set()
    _DISCOVERY = asyncio.Lock()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._wakes_init()
        self._reader = None
        self._store_version = None
        self._discovery_version = None
        self._candidates = []
        self._discovery_failed = False

    async def stop(self):
        self._CLAIMED.discard(getattr(self, "_session_id", "") or "")
        await super().stop()

    def build_command(self) -> list[str]:
        cmd = list(self.att["command"]) or ["opencode"]
        if self.resume and self.att.get("cli_session") and "--session" not in cmd and "-s" not in cmd:
            cmd += ["--session", self.att["cli_session"]]
        return cmd

    def _connect(self) -> sqlite3.Connection:
        if self._reader is None:
            self._reader = sqlite3.connect(f"{STORE.as_uri()}?mode=ro", uri=True)
        return self._reader

    def _find_session(self) -> str | None:
        self._discovery_failed = False
        if self.resume and (session_id := self.att.get("cli_session")):
            return str(session_id) if session_id not in self._CLAIMED else None
        if not STORE.exists():
            return None
        cutoff = int((self.spawned_at - 2) * 1000)
        try:
            with contextlib.nullcontext(self._connect()) as db:
                version = db.execute("PRAGMA data_version").fetchone()[0]
                if version != self._discovery_version:
                    self._candidates = db.execute(
                        "SELECT id FROM session WHERE directory = ? AND time_created >= ? "
                        "ORDER BY time_created DESC",
                        (self.att["cwd"], cutoff),
                    ).fetchall()
                    self._discovery_version = version
        except sqlite3.Error:
            self._discovery_failed = True
            return None
        for (session_id,) in self._candidates:
            if session_id not in self._CLAIMED:
                return str(session_id)
        return None

    def _briefing_ingested(self, session_id: str) -> bool:
        """The current TUI is ready only after its startup input is a user part."""
        try:
            with contextlib.nullcontext(self._connect()) as db:
                rows = db.execute(
                    "SELECT part.data FROM part "
                    "JOIN message ON message.id = part.message_id "
                    "WHERE part.session_id = ? "
                    "AND json_extract(message.data, '$.role') = 'user' "
                    "AND json_extract(part.data, '$.type') = 'text'",
                    (session_id,),
                ).fetchall()
        except sqlite3.Error:
            return False
        for (raw,) in rows:
            try:
                if self._claim_token in json.loads(raw).get("text", ""):
                    return True
            except (TypeError, json.JSONDecodeError, AttributeError):
                continue
        return False

    def _resume_probe(self) -> str:
        """Start resumed input with a fresh transcript-verifiable handshake."""
        prompt = (
            "Partyline resume check. Reply with READY, then wait for the next "
            "instruction; do not continue prior work from this check."
        )
        return self._with_claim(prompt)

    @watch_files(lambda self: [STORE])
    async def _run(self):
        try:
            await self._run_session()
        finally:
            if self._reader is not None:
                self._reader.close()
                self._reader = self._store_version = self._discovery_version = None

    async def _run_session(self):
        await asyncio.sleep(3.0)
        if not self.alive():
            return

        session_id = None
        lock = contextlib.nullcontext() if self.resume else self._DISCOVERY
        async with lock:
            if not self.resume:
                await self.send_keys(self.briefing())
            deadline = self.event_time() + 45.0
            waited = 0.0
            wake = StoreWake(self)
            while session_id is None and self.alive():
                observed = wake.observed()
                session_id = self._find_session()
                wake.read(observed, bool(session_id), error=self._discovery_failed)
                if session_id:
                    self._CLAIMED.add(session_id)
                    self._session_id = session_id
                    break
                delay = max(0, deadline - self.event_time())
                if wake.delay() is not None:
                    delay = min(delay, wake.delay())
                await self.wait_for_change(delay)
                waited = 45.0 - max(0, deadline - self.event_time())
                if waited >= 45.0:
                    await self.post(
                        "system", "system",
                        f"{self.att['name']}: no session appeared after 45s — run the CLI "
                        f"once in {self.att['cwd']}, then re-attach.",
                    )
                    return
        if not session_id:
            return
        if self.resume:
            await self.send_keys(self._resume_probe())
            last_resume_probe = time.monotonic()
        if self.on_cli_session:
            self.on_cli_session(session_id)
        # The session id is claimed before polling its parts. A restart
        # orchestrator can now start the next process without discovery races.
        # Do not repeat old parts when reconnecting to an existing session.
        started_ms = int((self.spawned_at - 1) * 1000)
        seen: set[str] = set()
        seen_boundaries: set[str] = set()
        # Assistant rows that never completed: in flight, or an aborted turn.
        # The next row in the session proves which — an abort writes no
        # completing row, so supersession is its only deterministic end.
        abandoned: dict[str, int] = {}
        seen_user_parts: set[str] = set()
        briefing_ready = False
        wake = StoreWake(self)
        while self.alive():
            observed = wake.observed()
            try:
                with contextlib.nullcontext(self._connect()) as db:
                    version = db.execute("PRAGMA data_version").fetchone()[0]
                    changed = version != self._store_version
                    if not changed:
                        rows, boundaries, user_parts = [], [], []
                    else:
                        rows = db.execute(
                            "SELECT part.id, part.data FROM part "
                            "JOIN message ON message.id = part.message_id "
                            "WHERE part.session_id = ? AND part.time_created >= ? "
                            "AND json_extract(message.data, '$.role') = 'assistant' "
                            "AND json_extract(message.data, '$.time.completed') IS NOT NULL "
                            "AND json_extract(part.data, '$.type') = 'text' "
                            "ORDER BY part.time_created, part.id",
                            (session_id, started_ms),
                        ).fetchall()
                        boundaries = db.execute(
                            "SELECT id, time_created, json_extract(data, '$.role'), "
                            "json_extract(data, '$.finish'), "
                            "json_extract(data, '$.time.completed') IS NOT NULL, data FROM message "
                            "WHERE session_id = ? AND time_created >= ? "
                            "AND json_extract(data, '$.role') IN ('user', 'assistant') "
                            "ORDER BY time_created, id",
                            (session_id, started_ms),
                        ).fetchall()
                        # The pasted digest lives in a user-message *part*: the
                        # message rows are empty shells, so the claim token is
                        # only visible here. Observed before any relay — speech
                        # posted before the gate opens is dropped and `seen`
                        # never retries it.
                        user_parts = db.execute(
                            "SELECT part.id, part.data FROM part "
                            "JOIN message ON message.id = part.message_id "
                            "WHERE part.session_id = ? AND part.time_created >= ? "
                            "AND json_extract(message.data, '$.role') = 'user' "
                            "AND json_extract(part.data, '$.type') = 'text'",
                            (session_id, started_ms),
                        ).fetchall()
                    for part_id, raw_part in user_parts:
                        self.observe_claim(raw_part)
                        await self._observe_user_part(raw_part, part_id=part_id)
                    self._store_version = version
                found = (any(part_id not in seen for part_id, _ in rows)
                         or any(part_id not in seen_user_parts for part_id, _ in user_parts)
                         or any(ident not in seen_boundaries and (completed or ident not in abandoned)
                                for ident, _, _, _, completed, _ in boundaries))
                seen_user_parts.update(part_id for part_id, _ in user_parts)
                wake.read(observed, found)
            except sqlite3.Error as exc:
                wake.read(observed, False, error=True)
                logger.debug("opencode poll skipped: %s", exc)
                await self.wait_for_change(wake.delay())
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
            for message_id, created_ms, role, finish, completed, raw in boundaries:
                # Message boundaries may carry the claim token; paste proof
                # comes from the ID-tracked user parts above.
                if role == "user":
                    self.observe_claim(raw)
                if role == "assistant" and not completed:
                    abandoned[message_id] = created_ms
                    continue
                # Supersession is ordered by time, not by poll: a row only
                # ends an abandoned turn when the store wrote it afterwards.
                for dead, dead_ms in list(abandoned.items()):
                    if dead_ms >= created_ms:
                        continue
                    del abandoned[dead]
                    if dead in seen_boundaries:
                        continue
                    seen_boundaries.add(dead)
                    await receipt(self.att, ENDED)
                    self._schedule_unproved_repool()
                if message_id in seen_boundaries:
                    continue
                seen_boundaries.add(message_id)
                if event := boundary_event(role, finish):
                    await receipt(self.att, event)
                    # Install the turn's busy state before readiness schedules
                    # any queued wake retry through Presence.
                    if (
                        event == BEGAN
                        and not briefing_ready
                        and self._briefing_ingested(session_id)
                    ):
                        briefing_ready = True
                        self.mark_ready()
                    if event == ENDED:
                        self._schedule_unproved_repool()
            if (
                self.resume
                and not briefing_ready
                and time.monotonic() - last_resume_probe >= RESUME_PROBE_INTERVAL
            ):
                # A paste during TUI startup can be lost. Retry the structured
                # handshake; only its fresh user part opens readiness.
                await self.send_keys(self._resume_probe())
                last_resume_probe = time.monotonic()
            await self.wait_for_change(wake.delay())
