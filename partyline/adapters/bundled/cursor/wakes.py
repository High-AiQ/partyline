"""Settle pasted wakes against Cursor's transcript, never against the paste itself.

Cursor's ``agent`` TUI takes a paste while a tool call is running and does
one of two things with it: drops it, or queues it until the turn ends. The
adapter used to credit every paste at once and fire a "turn began" receipt
for it. On 2026-09-13 a captain's *halt* order and two follow-ups were
pasted into a Cursor that was eighteen minutes into a GPU sweep; partyline
recorded all three as delivered, the transcript never saw any of them, and
the worker relaunched the job three times. A probe reproduced it: a stop
pasted mid-``sleep`` vanished, Escape did not cancel the tool, and a later
mention surfaced only after the turn ended.

So a wake is credited only when a transcript ``user`` record contains its
digest. A wake still outstanding when the turn ends was never ingested; it
is re-pooled and re-delivered once the CLI is idle, with one notice on the
line.

A second probe (2026-09-14) found the way in. Cursor's own docs: "pressing
Enter while the agent works sends your queued message into the active run
at a safe boundary to steer it, and only interrupts the turn if you press
Enter again"; "follow-ups move running tools to the background instead of
killing them". Observed: a paste plus one Enter sits in a steer queue for
as long as the tool runs; a second bare Enter delivers it at once as a new
user record while the tool keeps running in the background; one Ctrl+C
ends the turn ("Wait skipped", a ``turn_ended`` record) and leaves the CLI
alive, warning that a second Ctrl+C exits. So a wake pasted mid-turn gets
the second Enter, and ``@!name`` is exactly one Ctrl+C, confirmed from the
transcript.
"""

from __future__ import annotations

import asyncio
import logging
import time

from partyline.adapters.receipts import BEGAN, receipt
from partyline.interrupts import InterruptStatus

logger = logging.getLogger(__name__)
REPOOL_GRACE = 2.0
MAX_NOTICES = 3
# The queued steer is submitted by a second Enter a beat after the paste.
STEER_SUBMIT_DELAY = 0.5
CTRL_C = b"\x03"
# One Ctrl+C stops the turn; a second inside Cursor's "press again to exit"
# window kills the process. No interrupt may follow another this closely.
CTRL_C_EXIT_WINDOW = 5.0
CONFIRM_TIMEOUT = 10.0


def _normal(text: str) -> str:
    return " ".join(text.split())


class WakeSettlement:
    """Mixin for the Cursor adapter: prove a wake or retry it while idle."""

    _turn_open: bool = False
    _outstanding: list[tuple[str, float, tuple[int, ...], bool]]
    _notices: int = 0
    _settle_task: asyncio.Task | None = None

    def _wakes_init(self) -> None:
        self._outstanding = []
        self._turn_open = False
        self._notices = 0
        self._settle_task = None
        self._last_ctrl_c = 0.0
        self.turn_ended_event = asyncio.Event()

    async def deliver(self, messages: list[dict]):
        digest = self.format_digest(messages)
        ids = tuple(m["id"] for m in messages if isinstance(m.get("id"), int))
        mid_turn = self._turn_open
        await super().deliver(messages)  # type: ignore[misc]
        if not digest.strip():
            return None
        if mid_turn and self.alive():  # type: ignore[attr-defined]
            # The paste is now a queued steer; the second Enter sends it into
            # the run immediately, with the running tool backgrounded.
            await asyncio.sleep(STEER_SUBMIT_DELAY)
            self.write_terminal(b"\r")  # type: ignore[attr-defined]
        if not mid_turn:
            # Only an idle CLI starts a turn from a paste; claiming one for a
            # busy CLI is how the lost halt order read as "acted on".
            await receipt(self.att, BEGAN)  # type: ignore[attr-defined]
        if not ids:
            return None
        self._outstanding.append((digest, time.time(), ids, mid_turn))
        return False  # pasted, unproven: the transcript decides the credit

    async def _note_user_input(self, content: str) -> None:
        """A transcript user record: credit every outstanding wake it contains."""
        self._turn_open = True
        text = _normal(content)
        kept = []
        for wake in self._outstanding:
            digest, _pasted_at, ids, _mid = wake
            if _normal(digest) in text:
                confirm = self.att.get("confirm_delivery_ids")  # type: ignore[attr-defined]
                if confirm is not None:
                    await confirm(list(ids))
                continue
            kept.append(wake)
        self._outstanding = kept

    def _note_turn_ended(self) -> None:
        self._turn_open = False
        self.turn_ended_event.set()
        if self._outstanding and (self._settle_task is None or self._settle_task.done()):
            self._settle_task = asyncio.create_task(self._settle_turn_end())

    async def interrupt(self) -> InterruptStatus:
        """One Ctrl+C, confirmed by the transcript's turn-end record."""
        if not self.alive():  # type: ignore[attr-defined]
            return "unconfirmed"
        if not self._turn_open:
            return "idle"
        if time.time() - self._last_ctrl_c < CTRL_C_EXIT_WINDOW:
            return "unconfirmed"  # a second press now would exit the CLI
        self.turn_ended_event.clear()
        self._last_ctrl_c = time.time()
        self.write_terminal(CTRL_C)  # type: ignore[attr-defined]
        try:
            await asyncio.wait_for(self.turn_ended_event.wait(), timeout=CONFIRM_TIMEOUT)
        except TimeoutError:
            return "unconfirmed"
        return "interrupted"

    async def _settle_turn_end(self) -> None:
        """A wake still outstanding after the turn was never ingested: re-pool it."""
        doomed = [wake for wake in self._outstanding]
        await asyncio.sleep(REPOOL_GRACE)
        survivors = [wake for wake in self._outstanding if wake in doomed]
        self._outstanding = [wake for wake in self._outstanding if wake not in doomed]
        if not survivors or not self.alive():  # type: ignore[attr-defined]
            return
        ids = [message_id for wake in survivors for message_id in wake[2]]
        repool = self.att.get("repool_message_ids")  # type: ignore[attr-defined]
        if repool is not None:
            await repool(ids)
        if self._notices < MAX_NOTICES:
            self._notices += 1
            await self.post(  # type: ignore[attr-defined]
                "system", "system",
                f"{self.att['name']}: a wake pasted while Cursor was busy never reached "  # type: ignore[attr-defined]
                "the model — re-delivering now that it is idle",
            )
