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

from partyline.adapters import Adapter
from partyline.adapters.receipts import BEGAN, ENDED, receipt
from partyline.adapters.bundled.opencode.wakes import WakeSettlement

logger = logging.getLogger(__name__)


STORE = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
RESUME_PROBE_INTERVAL = 5.0


def boundary_event(role: str | None, finish: str | None) -> str | None:
    """The turn boundary one message row represents, if any.

    ``tool-calls`` means the loop continues with another step; anything else
    on a completed assistant message means the CLI is waiting for input again.
    """
    if role == "user":
        return BEGAN
    if role == "assistant" and finish != "tool-calls":
        return ENDED
    return None


class PartylineAdapter(WakeSettlement, Adapter):
    kind = "opencode"

    # A session created by a fresh TUI has no caller-supplied identifier.  Do
    # discovery one at a time and claim the result so concurrent attachments in
    # one directory never tail the same transcript.
    _CLAIMED: set[str] = set()
    _DISCOVERY = asyncio.Lock()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._wakes_init()

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
            with contextlib.closing(self._connect()) as db:
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

    def _briefing_ingested(self, session_id: str) -> bool:
        """The current TUI is ready only after its startup input is a user part."""
        try:
            with contextlib.closing(self._connect()) as db:
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
        briefing_ready = False
        while self.alive():
            try:
                with contextlib.closing(self._connect()) as db:
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
            except sqlite3.Error as exc:
                logger.debug("opencode poll skipped: %s", exc)
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
            await asyncio.sleep(0.5)
