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
* Handing off to *any* live process settles the turn: delegating onward
  means the work is still moving and the requester's next signal comes
  from the end of that chain, not from a false "finished".
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
* A turn that says nothing owes nothing. Words said before the wake are not
  this turn's words either. On the first fleet trial, silent ends were
  the process reading a passing mention and having nothing to add, and
  the "last words" quoted were a greeting from before the wake.
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

from .mention_relay import LIVE, is_foreign, post_private, reaches_a_process, speaker_attachment
from .mentions import addressees, mentioned_names

EXCERPT = 280
# Long enough for a transcript tail to post the turn's last message after the
# harness receipt, short enough that a manager is not kept waiting.
RETURN_GRACE_SECONDS = 3.0


def excerpt(body: str | None) -> str:
    """A one-line quote whose mentions cannot ring anyone.

    The notice is routed on purpose, so a quoted ``@name`` would wake that
    name on the requester's line — a second, accidental hand-off. The
    fullwidth sign reads the same and is not a mention.
    """
    if not body:
        return ""
    text = " ".join(body.split()).replace("@", "＠")
    return text if len(text) <= EXCERPT else text[: EXCERPT - 1].rstrip() + "…"


class ReturnPath:
    """Per-attachment memory of who asked and whether anyone was answered."""

    def __init__(self, runtime):
        self.runtime = runtime
        self.grace = RETURN_GRACE_SECONDS
        # att_id -> requester attachment id -> its row at wake time, plus the
        # id of the message that rang this process, so a notice can point at
        # everything said since.
        self.requesters: dict[str, dict[str, dict]] = {}
        # att_id -> human handle -> the line the human typed on
        self.askers: dict[str, dict[str, str]] = {}
        self.addressed: set[str] = set()
        self.last_said: dict[str, str] = {}
        # att_id -> the return decision waiting out its grace
        self.pending: dict[str, asyncio.Task] = {}

    def _row(self, att_id: str) -> dict | None:
        """The attachment's durable row; a runtime with no database has no return path."""
        db = getattr(self.runtime, "db", None)
        return db.get_attachment(att_id) if db is not None else None

    def forget(self, att_id: str) -> None:
        for table in (self.requesters, self.askers, self.last_said):
            table.pop(att_id, None)
        self.addressed.discard(att_id)
        if task := self.pending.pop(att_id, None):
            task.cancel()

    def note_delivered(self, att_id: str, messages: list[dict]) -> None:
        """Record who woke this process from the batch that was pasted."""
        me = self._row(att_id)
        if me is None:
            return
        self.last_said.pop(att_id, None)  # what was said before the wake is not an answer
        for message in messages:
            if me["name"].lower() not in addressees(str(message.get("body") or "")):
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
            elif kind == "human" and is_foreign(message):
                self.askers.setdefault(att_id, {})[message["sender"]] = message["source_conv_id"]

    def note_spoke(self, att_id: str, body: str) -> None:
        """The process said something; a mention of a live process settles the turn."""
        me = self._row(att_id)
        if me is None:
            return
        self.last_said[att_id] = body
        if reaches_a_process(self.runtime.db, me, mentioned_names(body)):
            self.addressed.add(att_id)
            if task := self.pending.pop(att_id, None):
                task.cancel()  # the last words handed off after all

    async def turn_ended(self, att_id: str) -> None:
        """The harness closed the turn: settle the return once its grace is up."""
        if att_id in self.pending or not (self.requesters.get(att_id) or self.askers.get(att_id)):
            return
        if att_id in self.addressed:
            self._clear(att_id)
            return
        self.pending[att_id] = asyncio.create_task(self._settle(att_id))

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
        return state

    async def _settle(self, att_id: str) -> list[dict]:
        await asyncio.sleep(self.grace)
        self.pending.pop(att_id, None)
        requesters, askers, said = self._clear(att_id)
        finisher = self._row(att_id)
        if finisher is None or not said:
            return []
        posted = []
        for requester in requesters.values():
            current = self.runtime.db.get_attachment(requester["id"])
            if current is None or current["status"] not in LIVE:
                continue
            if finisher.get("is_lead") and not current.get("is_lead"):
                continue
            body = self._notice(
                current["name"], finisher, current["conv_id"], said, requester["since_id"]
            )
            posted.append(await post_private(
                self.runtime, current["conv_id"], "system", "system", body,
                audience=current["id"], source=(att_id, finisher["conv_id"]),
            ))
        for handle, line_id in askers.items():
            body = self._notice(handle, finisher, line_id, said)
            posted.append(await self.runtime.post_message(line_id, "system", "system", body))
        return posted

    def _notice(
        self, to: str, finisher: dict, on_line: str, said: str, since_id: int | None = None
    ) -> str:
        where = pointer = ""
        if finisher["conv_id"] != on_line:
            line = self.runtime.db.get_conversation(finisher["conv_id"]) or {}
            where = f" on line «{line.get('name', '?')}»"
            if since_id is not None:  # everything since the wake, in one call
                pointer = (f". Read it all: GET /api/conversations/{finisher['conv_id']}"
                           f"/messages?after_id={since_id - 1}")
        tail = f"; last said: «{excerpt(said)}»"
        # The finisher is named without the sigil: this notice must not wake it.
        return (
            f"↩ @{to} — {finisher['name']}{where} ended its turn without handing off "
            f"to any process{tail}{pointer}"
        )
