"""Who is working right now, told by the server rather than by the process.

A mentioned process is working from the moment it is woken, but nothing it
writes reaches the line until its turn ends. For an evening's worst
failures — a lead reassigning work mid-build, two agents writing the same
files — the room could not tell thinking from dead.

**A process can never post its own liveness**, which is the whole point: a
signal the subject can forge is not evidence (`docs/lessons.md`).

The subtler version of that mistake is what this module used to do: speech
was treated as the end of a turn, so "ack, on it" cleared the badge while
the work had not started. **Speech never ends a turn.** A turn ends when
the harness says it ended, or when the process dies.

Those receipts come in pairs: ``began`` when the CLI starts a turn, ``ended``
when it finishes. Pairing makes them robust to a CLI that folds two digests
into one turn — one pair, not two — so the badge neither wedges on nor
flickers between turns. A harness that reports them arms only on ``began``:
a swallowed paste never started a turn, and arming on the write is the
stuck "working…" a silent paste produces.

A harness with no such receipt still arms on the pasted wake — the only
signal it will ever observe — and never self-clears. A guess about when a
turn ended is a new way to be wrong; the client can lower its confidence
from ``since`` without the server asserting an ending it never observed.

Nothing here reaches into ``ChatRuntime``: presence wraps the callbacks and
the adapter the server already builds.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .presence_contracts import WorkingEvent

WORKING = "working"
SPEAKING = "speaking"
IDLE = "idle"

# Adapters whose harness reports turn ends from its own transcript; everything
# else is ``none`` and arms on delivery, never self-clearing. ``quiet`` is
# reserved on the wire for a guessed ending and deliberately has no emitter:
# silence after an ack is the very bug this module exists to remove.
RECEIPT = "receipt"
NONE = "none"


@dataclass
class Turn:
    """One attachment's open turn, on one line."""

    conv_id: str
    since: float
    turn: int
    phase: str
    # Harness turn-start receipts awaiting their matching end: a CLI folding
    # two wakes into one turn emits one pair, so this counts the harness's
    # own boundaries rather than our deliveries.
    open: int = 0
    # The server generation that owned the attachment when the turn opened;
    # a receipt from a previous owner must not end the current turn.
    owner: str | None = None


class Presence:
    """Which attachments are mid-turn, and the broadcasts that say so."""

    def __init__(self, runtime):
        self.runtime = runtime
        # attachment id -> its open turn. The line is part of the state
        # because presence is asked per-conversation: a tab on one line must
        # never light a jack belonging to another.
        self.turns: dict[str, Turn] = {}
        # Monotonic per attachment, bumped on every announcement. A turn
        # number cannot order transitions *within* a turn, and working →
        # speaking → working is exactly that.
        self.revisions: dict[str, int] = {}
        self.counts: dict[str, int] = {}
        # Which line an attachment belongs to, kept after its turn closes so
        # a snapshot can carry an idle tombstone rather than an absence.
        self.lines: dict[str, str] = {}
        self.completions: dict[str, str] = {}

    def register(self, att_id: str, completion: str) -> None:
        """Record how this attachment's harness reports the end of a turn."""
        self.completions[att_id] = completion

    def completion(self, att_id: str) -> str:
        return self.completions.get(att_id, NONE)
    def is_working(self, att_id: str) -> bool:
        return att_id in self.turns

    def phase(self, att_id: str) -> str:
        turn = self.turns.get(att_id)
        return turn.phase if turn else IDLE

    def working_ids(self, conv_id: str) -> list[str]:
        """Which attachments are mid-turn *on this line*."""
        return sorted(
            att_id for att_id, turn in self.turns.items() if turn.conv_id == conv_id
        )

    def snapshot(self, conv_id: str) -> list[dict]:
        """Every attachment's presence on this line, open turns and finished.

        The events describe transitions, so a browser opening while someone
        is thinking would otherwise show nothing until that turn ended.

        Finished turns are reported too, as ``idle`` carrying the revision
        that closed them. Raised by @sol: a client buffering events while its
        snapshot is in flight cannot order a held ``working`` against an
        attachment the snapshot omits, so the stale event would resurrect a
        badge that had already gone out.
        """
        states = []
        for att_id, line in sorted(self.lines.items()):
            if line != conv_id:
                continue
            turn = self.turns.get(att_id)
            states.append(
                {
                    "id": att_id,
                    "phase": turn.phase if turn else IDLE,
                    "completion": self.completion(att_id),
                    # A closed turn has no start time; the client reads phase
                    # first and only derives age for an open one.
                    "since": turn.since if turn else 0.0,
                    "turn": self.counts.get(att_id, 0),
                    "revision": self.revisions.get(att_id, 0),
                }
            )
        return states

    async def _announce(self, conv_id: str, att_id: str, phase: str) -> None:
        revision = self.revisions.get(att_id, 0) + 1
        self.revisions[att_id] = revision
        open_turn = self.turns.get(att_id)
        await self.runtime.broadcast(
            conv_id,
            WorkingEvent(
                attachment_id=att_id,
                working=phase in (WORKING, SPEAKING),
                phase=phase,
                completion=self.completion(att_id),
                since=open_turn.since if open_turn else 0.0,
                turn=self.counts.get(att_id, 0),
                revision=revision,
            ),
        )

    def _current(self, att_id: str, owner: str | None, turn: int | None) -> Turn | None:
        """The open turn a receipt may act on, if it may act at all.

        A receipt naming a turn or an owner must name *this* one, which closes
        the two ways a stale signal could clear a live badge: a hook fired by
        a previous server generation, and a completion for a superseded turn.
        """
        open_turn = self.turns.get(att_id)
        if open_turn is None:
            return None
        if turn is not None and turn != open_turn.turn:
            return None
        if owner is not None and open_turn.owner is not None and owner != open_turn.owner:
            return None
        return open_turn

    async def started(self, conv_id: str, att_id: str, owner: str | None = None) -> None:
        """A wake was delivered into this attachment's terminal.

        This arms the badge rather than declaring a turn: the CLI has not
        read the paste yet. A second wake mid-turn is not a new turn.
        """
        if att_id in self.turns:
            return
        self.counts[att_id] = self.counts.get(att_id, 0) + 1
        self.lines[att_id] = conv_id
        self.turns[att_id] = Turn(
            conv_id=conv_id, since=time.time(), turn=self.counts[att_id], phase=WORKING, owner=owner
        )
        await self._announce(conv_id, att_id, WORKING)

    async def began(
        self, conv_id: str, att_id: str, owner: str | None = None, turn: int | None = None
    ) -> None:
        """The harness reports the CLI has begun a turn.

        Arms the badge if a delivery has not, and records the open boundary
        so the matching end knows whether anything is still running.
        """
        open_turn = self._current(att_id, owner, turn)
        if open_turn is None:
            if turn is not None or att_id in self.turns:
                return  # a receipt for a turn that is not the open one
            await self.started(conv_id, att_id, owner)
            open_turn = self.turns[att_id]
        open_turn.open += 1

    async def ended(
        self, conv_id: str, att_id: str, owner: str | None = None, turn: int | None = None
    ) -> None:
        """The harness reports the CLI has finished a turn.

        Only closes the turn once every observed start has its end, so a CLI
        that took two wakes as two turns stays lit through both.
        """
        open_turn = self._current(att_id, owner, turn)
        if open_turn is None:
            return
        open_turn.open = max(0, open_turn.open - 1)
        if open_turn.open == 0:
            await self.finished(conv_id, att_id)

    async def spoke(self, conv_id: str, att_id: str) -> None:
        """The process said something. It is still working, just audible.

        The transition the badge used to get wrong. It exists so the client
        can tell thinking from mid-reply, and so a test can pin that an ack
        changes the phase and nothing else.
        """
        open_turn = self.turns.get(att_id)
        if open_turn is None or open_turn.phase == SPEAKING:
            return
        open_turn.phase = SPEAKING
        await self._announce(conv_id, att_id, SPEAKING)

    async def finished(self, conv_id: str, att_id: str) -> None:
        """The turn is over: the harness said so, or the process is gone."""
        if self.turns.pop(att_id, None) is None:
            return  # not working: say nothing rather than announce a non-event
        await self._announce(conv_id, att_id, IDLE)

    def forget(self, att_id: str) -> None:
        """Drop state without broadcasting — for a line that is going away."""
        self.turns.pop(att_id, None)
        self.lines.pop(att_id, None)
        self.completions.pop(att_id, None)
        self.revisions.pop(att_id, None)
        self.counts.pop(att_id, None)

    def watch(self, adapter, conv_id: str, att_id: str, completion: str = NONE):
        """Return the adapter, with its wake delivery reporting presence.

        Wrapping ``deliver`` keeps the report where the fact is: the receipt
        fires only once the digest has actually been written into the pty,
        so a delivery that raises never claims a turn started.
        """
        deliver = adapter.deliver
        att = getattr(adapter, "att", None) or {}
        owner = att.get("runtime_owner")
        self.register(att_id, completion)

        async def delivering(messages):
            await deliver(messages)
            # A receipt harness arms on its own began, never on the paste.
            if self.completions.get(att_id) != RECEIPT:
                await self.started(conv_id, att_id, owner)

        adapter.deliver = delivering
        return adapter

    def posting(self, conv_id: str, att_id: str, post: Callable[..., Awaitable[None]]):
        """Wrap the runtime's post callback so speech is *reported*, not obeyed.

        Only ``agent`` output moves the phase. An adapter also posts *system*
        notices through this same callback — a resume's backlog notice, a
        transcript refusal — and those are the server talking about the
        process, not the process saying anything at all.

        What this deliberately does not do is end the turn. Speech is not an
        ending, and treating it as one is the bug this module was rewritten
        to remove.
        """

        async def posted(sender: str, sender_type: str, body: str):
            await post(sender, sender_type, body)
            if sender_type == "agent":
                await self.spoke(conv_id, att_id)

        return posted

    def statusing(
        self, conv_id: str, att_id: str, on_status: Callable[[str], Awaitable[None]]
    ):
        """Wrap the status callback so a stopped process stops looking busy.

        A process that dies mid-turn would otherwise pulse forever. Death is
        terminal for the turn: the transcript tail may keep posting, but that
        is delivery of words already written, not work still happening.
        """

        async def status(value: str):
            await on_status(value)
            if value in ("exited", "detached"):
                await self.finished(conv_id, att_id)

        return status
