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
"""

from __future__ import annotations

from .mention_relay import LIVE, is_foreign, post_private, reaches_a_process, speaker_attachment
from .mentions import addresses, mentioned_names

EXCERPT = 280


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
        # att_id -> requester attachment id -> its live row at wake time
        self.requesters: dict[str, dict[str, dict]] = {}
        # att_id -> human handle -> the line the human typed on
        self.askers: dict[str, dict[str, str]] = {}
        self.addressed: set[str] = set()
        self.last_said: dict[str, str] = {}

    def _row(self, att_id: str) -> dict | None:
        """The attachment's durable row; a runtime with no database has no return path."""
        db = getattr(self.runtime, "db", None)
        return db.get_attachment(att_id) if db is not None else None

    def forget(self, att_id: str) -> None:
        for table in (self.requesters, self.askers, self.last_said):
            table.pop(att_id, None)
        self.addressed.discard(att_id)

    def note_delivered(self, att_id: str, messages: list[dict]) -> None:
        """Record who woke this process from the batch that was pasted."""
        me = self._row(att_id)
        if me is None:
            return
        for message in messages:
            if not addresses(me["name"], [message]):
                continue
            kind = message.get("sender_type")
            if kind == "agent":
                origin = message.get("source_conv_id") or me["conv_id"]
                asker = speaker_attachment(self.runtime.db, origin, message)
                if asker is not None and asker["id"] != att_id:
                    self.requesters.setdefault(att_id, {})[asker["id"]] = asker
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

    async def turn_ended(self, att_id: str) -> list[dict]:
        """The harness closed the turn: ring every requester nobody answered."""
        requesters = self.requesters.pop(att_id, {})
        askers = self.askers.pop(att_id, {})
        said = self.last_said.pop(att_id, None)
        answered = att_id in self.addressed
        self.addressed.discard(att_id)
        finisher = self._row(att_id)
        if answered or finisher is None or not (requesters or askers):
            return []
        posted = []
        for requester in requesters.values():
            current = self.runtime.db.get_attachment(requester["id"])
            if current is None or current["status"] not in LIVE:
                continue
            if finisher.get("is_lead") and not current.get("is_lead"):
                continue
            body = self._notice(current["name"], finisher, current["conv_id"], said)
            posted.append(await post_private(
                self.runtime, current["conv_id"], "system", "system", body,
                audience=current["id"], source=(att_id, finisher["conv_id"]),
            ))
        for handle, line_id in askers.items():
            body = self._notice(handle, finisher, line_id, said)
            posted.append(await self.runtime.post_message(line_id, "system", "system", body))
        return posted

    def _notice(self, to: str, finisher: dict, on_line: str, said: str | None) -> str:
        where = ""
        if finisher["conv_id"] != on_line:
            line = self.runtime.db.get_conversation(finisher["conv_id"]) or {}
            where = f" on line «{line.get('name', '?')}»"
        tail = f"; last said: «{excerpt(said)}»" if said else " and said nothing"
        # The finisher is named without the sigil: this notice must not wake it.
        return (
            f"↩ @{to} — {finisher['name']}{where} ended its turn without handing off "
            f"to any process{tail}"
        )
