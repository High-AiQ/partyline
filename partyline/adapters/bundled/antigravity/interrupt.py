"""Stopping an Antigravity turn, and knowing that it stopped.

`Esc` cancels the active agent operation. The CLI records that: a
``SYSTEM``/``ERROR_MESSAGE`` step whose content reads *"Error: The stream was
interrupted. Please continue the task you were working on."* Confirming from
that record rather than from the keystroke matters — a pty write proves only
that bytes left, and Antigravity's own changelog records a period where input
typed straight after `Esc` was swallowed.

Read from the transcripts on this machine (28 conversations, ~8,300 steps) on
2026-09-09: no ``PLANNER_RESPONSE`` ever carries a cancelled, aborted or
failed status, so the interrupt is only visible here. That also corrects the
older note in ``adapter.py`` which concluded that aborts leave no record.

What an interrupt costs, so nobody reaches for it casually: tool results that
already landed remain in the transcript, but a tool still running when `Esc`
arrives produces no result record at all. The model is told to continue and
never receives the output it was waiting for. In the same transcripts, six
consecutive interrupts each drew an empty planner response and another
interrupt — this is a livelock if it is ever automated.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime

from partyline.interrupts import InterruptStatus

# Esc. Antigravity's first press cancels the active operation; it is not the
# exit key, which is a Ctrl+C double-press.
ESCAPE = b"\x1b"
CONFIRM_TIMEOUT = 10.0
# After the interruption notice, Antigravity answers with an empty planner
# response, which is what actually closes the turn. Confirming the notice
# alone would report success while the composer was still mid-turn.
SETTLE_TIMEOUT = 10.0
INTERRUPTED = "the stream was interrupted"


def record_time(created_at) -> float | None:
    """When a transcript step was written, or None without a usable stamp."""
    if not created_at:
        return None
    try:
        return datetime.fromisoformat(str(created_at).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def record_key(record: dict) -> str:
    """The identity the adapter's tail already dedups on."""
    return f"{record.get('step_index')}:{record.get('created_at')}"


def is_interrupt_record(
    record: object,
    since: float | None = None,
    used: set[str] | None = None,
) -> bool:
    """Whether this step is Antigravity's interruption notice, written since.

    ``since`` is the boundary: the transcript tail can be behind, so a notice
    from an *earlier* interruption may be read after this one's Esc and would
    otherwise confirm it. A record with no usable timestamp cannot be placed
    on either side of the boundary, so it does not confirm anything.

    The comparison is exact, with no tolerance either way. Antigravity writes
    this transcript on the same host that presses Esc, so both stamps come
    from one clock and there is no skew to absorb — and any tolerance is a
    window in which the *previous* interruption's notice confirms this one.
    Two bangs a second apart plus a lagging tail is enough to walk through a
    two-second allowance, which is why the earlier one was removed.

    ``used`` closes the same hole from the other side: a notice that has
    already confirmed an interruption can never confirm another. Between the
    two, a previous interruption's notice is rejected whether it arrives
    before this Esc (already used) or after it (older than the boundary), and
    neither check depends on how far behind the tail is running.
    """
    if not isinstance(record, dict):
        return False
    if record.get("source") != "SYSTEM" or record.get("type") != "ERROR_MESSAGE":
        return False
    if INTERRUPTED not in str(record.get("content") or "").lower():
        return False
    if used is not None and record_key(record) in used:
        return False
    if since is None:
        return True
    written = record_time(record.get("created_at"))
    return written is not None and written >= since


def turn_is_closed(adapter) -> bool:
    """Whether the adapter *knows* no turn is running.

    Three states, not two. ``False`` and "no idea" are different answers, and
    only a positive "closed" may skip the keystroke: assuming idle when the
    state is unknown would silently decline to interrupt a process that was
    working, which is the one thing `@!` exists to do.
    """
    return getattr(adapter, "_turn_open", None) is False


async def interrupt(
    adapter,
    timeout: float = CONFIRM_TIMEOUT,
    settle_timeout: float = SETTLE_TIMEOUT,
) -> InterruptStatus:
    """Press Esc, then wait for the turn to actually end.

    Two boundaries, and both are needed. The interruption notice proves Esc
    landed; the turn closing proves the composer is no longer mid-turn, which
    is the state a message may safely be pasted into — Antigravity accepts a
    mid-turn submission and silently drops it, which is how two mentions were
    lost on 2026-08-24.

    A turn that is already closed is answered without touching the pty at all.
    Esc cancels nothing there and Antigravity writes no notice, so waiting for
    one costs the full timeout before the message is delivered — ten seconds,
    measured on the live line on 2026-09-09, for a message that needed no
    interruption in the first place.

    Reports rather than raises when the process is gone or either boundary
    never arrives: an unconfirmed interrupt is a fact for the room, not an
    error for the caller, and the message is delivered regardless.
    """
    if not adapter.alive():
        return "unconfirmed"
    if turn_is_closed(adapter):
        return "idle"
    event = adapter.interrupt_confirmed
    event.clear()
    # Set before the keystroke: a notice written between the two must count.
    adapter.interrupt_since = time.time()
    adapter.write_terminal(ESCAPE)
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
    except TimeoutError:
        return "unconfirmed"
    return "interrupted" if await turn_closed(adapter, settle_timeout) else "unconfirmed"


async def turn_closed(adapter, timeout: float) -> bool:
    """Wait for the adapter to observe the turn ending, or give up saying so.

    Positive evidence only, the same rule as `turn_is_closed`. An adapter that
    does not track turn state can never satisfy this, so a fresh notice alone
    times out as unconfirmed rather than being reported as a closed turn — the
    notice proves Esc landed, not that the composer is free.
    """
    deadline = time.monotonic() + timeout
    while not turn_is_closed(adapter):
        if time.monotonic() >= deadline or not adapter.alive():
            return False
        await asyncio.sleep(0.05)
    return True
