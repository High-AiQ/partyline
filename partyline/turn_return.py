"""The return path: a turn a process asked for, that answered no process, bounces back.

Inside one harness, delegated work returns to its caller by construction: a
sub-agent's result is the caller's next input. Across harnesses on a line,
the only return was the worker remembering to ``@mention`` whoever asked. It
forgot constantly — a turn ends with "committed abc, tree clean", a routine
report with ``notify:false``, or a mention aimed at a handle on another
line — and the lead, whose goal it was, was never woken. Every prose reminder
and a fifteen-minute heartbeat failed to close that gap, because the lead
still had to *notice* silence. This closes it structurally.

The server already observes both halves. A wake digest says which processes
mentioned this one (its *requesters*); the harness receipt says when the
turn ended; the process's own posts say whether it handed off to anyone.
When a turn ends and nothing it said reached a live process, each requester
is rung with a short notice carrying what was last said, on the requester's
own line. The lead is woken by the fact that matters — "your worker
finished and the ball is with nobody" — not by a clock.

What keeps this a return rather than a second source of noise:

* The notice is a system message. It never counts as a requester, so a
  turn woken *only* by a notice owes nothing when it ends — one explicit
  wake yields at most one implicit reply, and no chain can run on its own.
* Handing off clears only the requesters that speech actually reaches.
  Delegating downward leaves an upstream requester owed; a later turn that
  addresses them clears them. This turn sends no "finished" notice while
  the work is moving, and a deferred notice is superseded by the hand-off.
* A manager wrapping up to a person does not bounce back to its
  implementers. The lead's terminal turn — "@operator the PR is up" — is the
  one case where a requester's silence is correct, so a manager's turn
  returns only to requesters that are managers themselves.
* Only a harness-reported ending returns. An exit or detach is announced
  on the line already and a fleet restart would ring every lead at once.
* Humans read their own line, so a human requester is told only when it
  asked from another line — an unrouted notice where it was typed.
* A request is a message *for* this process, not one that talks about it.
  "@lead please have @worker build it" rings worker too — every mention
  rings — but only lead's turn owes anything: the leading run of mentions
  names the addressees (`mentions.addressees`). Without this, every status
  line naming a worker made its author a requester, and the room filled
  with returns about turns nobody had asked for.
* A silent turn after an addressed wake is unanswered: each requester is
  told it said nothing, and a child captain also tells the parent line's
  captain. Words said before the wake are not this turn's words. A turn
  woken only by a notice still owes nothing, and the notice names the
  finisher without a sigil, so it never rings the finisher.
* A return rings only a requester that is waiting. A captain that acks
  "@lead on it" and keeps working has not stopped for an answer; ringing
  it with the lead's "holding" interrupted real work on the live run, and
  it answered "still holding" — one wasted turn per courtesy. So a return
  owed to a requester that is mid-turn is deferred until that turn ends,
  and dropped if the requester handed off to anyone in the meantime: its
  next signal supersedes the stale one.
* The decision waits a moment after the receipt. A harness reports the end
  of a turn through one channel and its last words through another (the
  transcript tail), and on the first live trial the receipt won by a few
  hundred milliseconds: the notice quoted "on it" while the findings landed
  one message later. The last words are the notice's payload, so the return
  is settled after a short grace, and speech that arrives inside it is
  quoted — or, if it hands off, cancels the notice.
"""

from __future__ import annotations

import asyncio

from .hierarchy import lead_attachment, parent_id_of
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
        if task := self.pending.pop(att_id, None):
            task.cancel()

    def note_delivered(self, att_id: str, messages: list[dict]) -> None:
        """Record who woke this process from the batch that was pasted."""
        me = self._row(att_id)
        if me is None:
            return
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
        owed = self.deferred.pop(att_id, [])
        said = self.last_said.get(att_id) or ""
        undeliverable = bool(
            finisher and said and is_undeliverable_closing(self.runtime.db, finisher, said)
        )
        handed_off = att_id in self.addressed and not undeliverable
        if handed_off:
            owed = []  # it handed off during the turn; the stale notices are superseded
        for line_id, body, source_att in owed:
            source = self._row(source_att) or {}
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
        await asyncio.sleep(self.grace)
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
            if self._working(current["id"]):
                self.deferred.setdefault(current["id"], []).append((current["conv_id"], body, att_id))
                continue
            posted.append(await post_private(
                self.runtime, current["conv_id"], "system", "system", body,
                audience=current["id"], source=(att_id, finisher["conv_id"]),
            ))
        for handle, line_id in askers.items():
            body = format_notice(self.runtime, handle, finisher, line_id, said)
            posted.append(await self.runtime.post_message(line_id, "system", "system", body))
        return posted
