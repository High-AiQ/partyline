"""State and delivery logic for the return path.

The protocol rationale lives in ``turn_return.py``.
"""

from __future__ import annotations

import asyncio
import time

from .hierarchy import lead_attachment, parent_id_of
from .goal_stall import wait_until_quiet
from .mention_relay import LIVE, is_foreign, post_private, reaches_a_process, speaker_attachment
from .mentions import addressees, line_addressed, mentioned_names
from .return_notice import format_notice, is_undeliverable_closing

# Long enough for a transcript tail to post the turn's last message after the
# harness receipt, short enough that a manager is not kept waiting.
RETURN_GRACE_SECONDS = 3.0


class ReturnPath:
    """Per-attachment memory of who asked and whether anyone was answered."""

    def __init__(self, runtime, presence=None):
        self.runtime = runtime
        self.presence = presence
        self.grace = RETURN_GRACE_SECONDS
        # requester att_id -> notices owed to it while it was mid-turn
        self.deferred: dict[str, list[tuple[str, str, str]]] = {}
        # att_id -> requester attachment id -> its row at wake time, plus the
        # id of the message that rang this process, so a notice can point at
        # everything said since.
        self.requesters: dict[str, dict[str, dict]] = {}
        # att_id -> human handle -> the line the human typed on
        self.askers: dict[str, dict[str, str]] = {}
        self.addressed: set[str] = set()
        self.last_said: dict[str, str] = {}
        # att_id woke by a process or a foreign human, not by a system notice
        self.real_wake: set[str] = set()
        # att_id whose silent settle should also tell the parent line's captain
        self.notify_parent: set[str] = set()
        # att_id -> the return decision waiting out its grace
        self.pending: dict[str, asyncio.Task] = {}
        self.ended_at: dict[str, float] = {}
        self.clock = time.monotonic
        self.sleep = asyncio.sleep

    def _row(self, att_id: str) -> dict | None:
        """The attachment's durable row; a runtime with no database has no return path."""
        db = getattr(self.runtime, "db", None)
        return db.get_attachment(att_id) if db is not None else None

    def forget(self, att_id: str) -> None:
        for table in (self.requesters, self.askers, self.last_said, self.deferred):
            table.pop(att_id, None)
        self.addressed.discard(att_id)
        self.real_wake.discard(att_id)
        self.notify_parent.discard(att_id)
        self.ended_at.pop(att_id, None)
        if task := self.pending.pop(att_id, None):
            task.cancel()

    def cancel_check(self, att_id: str) -> None:
        self.ended_at.pop(att_id, None)
        if task := self.pending.pop(att_id, None):
            task.cancel()

    def note_delivered(self, att_id: str, messages: list[dict]) -> None:
        """Record who woke this process from the batch that was pasted."""
        me = self._row(att_id)
        if me is None:
            return
        if messages:
            self.cancel_check(att_id)
        self.last_said.pop(att_id, None)  # what was said before the wake is not an answer
        woke = False
        for message in messages:
            body = str(message.get("body") or "")
            if me["name"].lower() not in addressees(body) | line_addressed(body):
                continue
            kind = message.get("sender_type")
            if kind == "agent":
                origin = message.get("source_conv_id") or me["conv_id"]
                asker = speaker_attachment(self.runtime.db, origin, message)
                if asker is not None and asker["id"] != att_id:
                    entry = self.requesters.setdefault(att_id, {}).setdefault(
                        asker["id"], {**asker, "since_id": message["id"]}
                    )
                    entry["since_id"] = min(entry["since_id"], message["id"])
                    woke = True
            elif kind == "human" and is_foreign(message):
                self.askers.setdefault(att_id, {})[message["sender"]] = message["source_conv_id"]
                woke = True
        if woke:
            self.real_wake.add(att_id)

    def _release_reached(self, att_id: str, body: str) -> None:
        """Drop requesters this speech addresses and can actually ring. The rest stay owed."""
        me = self._row(att_id)
        reqs = self.requesters.get(att_id)
        if me is None or not reqs:
            return
        names = addressees(body) | line_addressed(body)
        for req_id, req in list(reqs.items()):
            handle = str(req.get("name") or "").lower()
            if handle in names and reaches_a_process(self.runtime.db, me, {handle}):
                reqs.pop(req_id, None)
        if not reqs:
            self.requesters.pop(att_id, None)

    def _close_speech(self, att_id: str) -> None:
        """Forget this turn's words. Unreached requesters stay owed into the next one."""
        self.addressed.discard(att_id)
        self.last_said.pop(att_id, None)
        self.real_wake.discard(att_id)
        self.notify_parent.discard(att_id)

    def _parent_captain(self, finisher: dict) -> dict | None:
        """The live captain above this child captain, never the finisher itself."""
        if not finisher.get("is_lead"):
            return None
        parent = parent_id_of(self.runtime.db.get_conversation(finisher["conv_id"]))
        if not parent:
            return None
        manager = lead_attachment(self.runtime.db, parent)
        if manager and manager["status"] in LIVE and manager["id"] != finisher["id"]:
            return manager
        return None

    def note_spoke(self, att_id: str, body: str) -> None:
        """The process said something; a mention of a live process settles the turn."""
        me = self._row(att_id)
        if me is None:
            return
        self.last_said[att_id] = body
        self._release_reached(att_id, body)
        if reaches_a_process(self.runtime.db, me, mentioned_names(body) | line_addressed(body)):
            self.addressed.add(att_id)
            if task := self.pending.pop(att_id, None):
                task.cancel()  # the last words handed off after all
                self._close_speech(att_id)

    async def turn_ended(self, att_id: str) -> None:
        """The harness closed the turn: deliver what was deferred for this process,
        then settle its own return once the grace is up."""
        finisher = self._row(att_id)
        self.ended_at[att_id] = self.clock()
        owed = self.deferred.pop(att_id, [])
        said = self.last_said.get(att_id) or ""
        undeliverable = bool(
            finisher and said and is_undeliverable_closing(self.runtime.db, finisher, said)
        )
        handed_off = att_id in self.addressed and not undeliverable
        if handed_off and self.presence is not None:
            self.presence.goal_stall.handed_off(finisher)
        if handed_off:
            owed = []  # it handed off during the turn; the stale notices are superseded
        for line_id, body, source_att in owed:
            source = self._row(source_att) or {}
            if self.presence is not None:
                self.presence.goal_stall.return_notice(
                    self._row(att_id) or {}, source
                )
            await post_private(self.runtime, line_id, "system", "system", body,
                               audience=att_id, source=(source_att, source.get("conv_id")))
        if att_id in self.pending:
            return
        real = att_id in self.real_wake
        manager = lead_attachment(self.runtime.db, finisher["conv_id"]) if finisher else None
        line_captain = bool(
            undeliverable and manager and manager["status"] in LIVE
            and manager["id"] != att_id and not finisher.get("is_lead")
        )
        parent = self._parent_captain(finisher) if finisher and real and not said else None
        owed = bool(self.requesters.get(att_id) or self.askers.get(att_id) or line_captain or parent)
        # A hand-off, or a turn a notice alone woke, carries unreached requesters and
        # sends nothing. Silence after a real wake still owes those requesters.
        if handed_off or (not real and not line_captain) or not owed:
            if handed_off or (not real and not line_captain):
                self._close_speech(att_id)
            else:
                self._clear(att_id)
            return
        if parent:
            self.notify_parent.add(att_id)
        self.pending[att_id] = asyncio.create_task(self._settle(att_id))

    def _working(self, att_id: str) -> bool:
        return bool(self.presence is not None and self.presence.is_working(att_id))

    async def drain(self) -> None:
        """Wait out every pending grace — for tests and shutdown."""
        for task in list(self.pending.values()):
            await task

    def _clear(self, att_id: str) -> tuple[dict, dict, str | None]:
        state = (
            self.requesters.pop(att_id, {}),
            self.askers.pop(att_id, {}),
            self.last_said.pop(att_id, None),
        )
        self.addressed.discard(att_id)
        self.real_wake.discard(att_id)
        self.notify_parent.discard(att_id)
        return state

    def _add_parent(self, att_id: str, finisher: dict, requesters: dict) -> None:
        parent = self._parent_captain(finisher)
        if parent is None or parent["id"] in requesters or parent["id"] == att_id:
            return
        since = [row.get("since_id") for row in requesters.values() if row.get("since_id") is not None]
        requesters[parent["id"]] = {
            **parent,
            "since_id": min(since) if since else finisher.get("last_seen") or None,
        }

    async def _settle(self, att_id: str) -> list[dict]:
        await self.sleep(self.grace)
        ended_at = self.ended_at.get(att_id, self.clock())
        if not await wait_until_quiet(
            self.runtime, self.presence, att_id, ended_at, self.clock, self.sleep
        ):
            if self.pending.get(att_id) is asyncio.current_task():
                self.pending.pop(att_id, None)
            return []
        self.pending.pop(att_id, None)
        tell_parent = att_id in self.notify_parent
        requesters, askers, said = self._clear(att_id)
        finisher = self._row(att_id)
        if finisher is None:
            return []
        if said and is_undeliverable_closing(self.runtime.db, finisher, said) and not finisher.get("is_lead"):
            manager = lead_attachment(self.runtime.db, finisher["conv_id"])
            if manager and manager["status"] in LIVE and manager["id"] != att_id:
                if manager["id"] not in requesters:
                    requesters[manager["id"]] = {
                        **manager,
                        "since_id": finisher.get("last_seen") or None,
                    }
        elif not said and tell_parent:
            self._add_parent(att_id, finisher, requesters)
        posted = []
        for requester in requesters.values():
            if requester["id"] == att_id:
                continue
            current = self.runtime.db.get_attachment(requester["id"])
            if current is None or current["status"] not in LIVE:
                continue
            if finisher.get("is_lead") and not current.get("is_lead"):
                continue
            body = format_notice(
                self.runtime, current["name"], finisher, current["conv_id"], said,
                requester.get("since_id"),
            )
            working = self._working(current["id"])
            if self.presence is not None:
                self.presence.goal_stall.return_notice(current, finisher, deferred=working)
            if working:
                self.deferred.setdefault(current["id"], []).append((current["conv_id"], body, att_id))
                continue
            posted.append(await post_private(
                self.runtime, current["conv_id"], "system", "system", body,
                audience=current["id"], source=(att_id, finisher["conv_id"]),
            ))
        for handle, line_id in askers.items():
            body = format_notice(self.runtime, handle, finisher, line_id, said)
            posted.append(await self.runtime.post_message(line_id, "system", "system", body))
        if self.presence is not None:
            await self.presence.goal_stall.check_tree(finisher["conv_id"])
        return posted
