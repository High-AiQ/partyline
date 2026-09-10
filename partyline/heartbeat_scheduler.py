"""The tick that turns a stored interval into an actual reminder.

Kept apart from `heartbeat`, which knows only rows and rules, so every timing
question can be tested against a fake clock and no test has to wait out a real
interval. The loop itself holds no state: everything that must survive a
restart is in the row, and everything that must survive a race is decided in
the single transaction that writes the reminder.

Delivery is deliberately *not* mention routing. The goal text is written by the
lead and could contain `@all` or someone else's handle; routing it would let a
private reminder wake the room on a timer. The reminder is handed to its owner
and to nobody else, through the same cursor-advancing path every other message
uses.
"""

from __future__ import annotations

import asyncio
import logging
import time

from . import heartbeat, heartbeat_snapshot, heartbeat_wake
from .contracts import MessageEvent
from .message_contracts import MessageResponse

logger = logging.getLogger(__name__)

# How often the loop looks, not how often it fires. Short enough that a
# reminder lands near its due time, long enough to be free.
TICK_SECONDS = 5.0


def deliverable_owner(runtime, row: dict) -> dict | None:
    """The owner, only while a reminder could actually reach it.

    The same three conditions `message_routing` uses — status exactly
    ``running``, a live adapter, a matching activation — plus the two this
    feature adds: the attachment is still on the line it enabled from, and
    that line is still a root line whose manager it still is. Roles and
    parentage both change at runtime, so eligibility is re-derived every tick
    rather than trusted from the row.

    A detached owner, or one that has lost the lead, is a *pause*: the tick
    posts nothing and the wake it may already be holding stays where it is.
    Waking somebody else instead would be the one thing a personal monitor
    must never do.
    """
    att = runtime.db.get_attachment(row["attachment_id"])
    if att is None or att["status"] != "running":
        return None
    if att["conv_id"] != row["conv_id"]:
        return None
    if not heartbeat.is_root_lead(runtime.db, row["conv_id"], att["id"]):
        return None
    adapter = runtime.live.get(att["id"])
    if adapter is None or not runtime.activation_matches(adapter, att):
        return None
    return att


class _GuardedAdapter:
    """The owner's adapter, with one condition attached to the paste itself.

    `deliver_pending` holds the delivery reservation across ``adapter.deliver``,
    so this is the last instant at which a reminder can still be called off —
    later than any check the scheduler can make, because awaits separate every
    outside check from the paste. Refusing here reads to `deliver_pending`
    exactly like an adapter that declined to paste: nothing is written and the
    cursor does not move.

    Wrapping rather than changing `deliver_pending` keeps this condition where
    it belongs. Every other caller delivers for a reason that cannot expire
    mid-await, and none of them should grow a parameter for one that can.
    """

    def __init__(self, adapter, guard):
        self._adapter = adapter
        self._guard = guard

    def __getattr__(self, name):
        return getattr(self._adapter, name)

    async def deliver(self, messages):
        if not self._guard():
            return False
        return await self._adapter.deliver(messages)


async def _deliver_claimed(
    runtime, attachment_id: str, generation: int, message_id: int
) -> None:
    """Hand this owner what it has not seen — if this is still its reminder.

    Everything before this point happened across at least one `await`, and a
    lot can change inside one: the monitor can be disabled, re-pointed, or
    re-enabled from another connection, the owner can detach, be replaced, or
    have its row removed outright. Re-deriving eligibility here, and matching
    both the generation and the exact message id, is what stops a tick that was
    correct when it started from delivering for a configuration that no longer
    exists.

    `deliver_pending` is the ordinary delivery path: it pastes from the durable
    cursor and advances it only once the paste is real, which is what makes a
    settled wake mean delivered rather than posted.
    """
    def still_ours() -> bool:
        """Everything that made this delivery correct, re-asked from scratch.

        Both halves matter and neither implies the other: the configuration
        must still be the one that claimed this message, *and* the owner must
        still be reachable. A detach does not change the row, and a disable
        does not stop the process — so asking only one question leaves the
        other's race open, which is how detach survived the first version.
        """
        current = heartbeat.get(runtime.db)
        if current is None or not current["enabled"]:
            return False
        if current["generation"] != generation:
            return False
        if current["pending_message_id"] != message_id:
            return False
        owner = deliverable_owner(runtime, current)
        if owner is None or owner["id"] != attachment_id:
            return False
        # Not merely *an* adapter for this attachment: the one this delivery
        # was decided against. A replacement is a different process that was
        # never the intended reader, and `activation_matches` alone would
        # accept it the moment it adopted the row.
        return runtime.live.get(owner["id"]) is captured

    captured = runtime.live.get(attachment_id)
    if captured is None or not still_ours():
        return
    owner = runtime.db.get_attachment(attachment_id)
    # The same question again, asked at the paste. Between the check above and
    # the write there is at least one await, and a disable can land in it; only
    # an answer taken while the delivery reservation is held is final.
    await runtime.deliver_pending(
        owner["conv_id"], owner, _GuardedAdapter(captured, still_ours)
    )


def _stay_quiet(runtime, row: dict, now: float) -> bool:
    """Decide not to wake the lead, because there is nothing to wake it about.

    This is the whole answer to the overnight failure: sixty reminders that
    each said only what the lead already knew. A wake is now earned by the
    state, not by the clock.

    A skip still costs the interval — `next_due_at` moves — but never the
    delta: `since_id` stays where it is, so the first wake that does fire
    reports everything accumulated since the lead last actually read one.

    Silence is not always innocent. A line holding open tasks with nothing to
    show for it across `STALL_AFTER_QUIET` checks is exactly the stall this
    monitor exists to notice, so that one breaks the quiet.
    """
    if not row["quiet_if_unchanged"]:
        return False
    snapshot = heartbeat_snapshot.build(
        runtime.db, row["conv_id"], row["since_id"], row["attachment_id"]
    )
    if heartbeat_snapshot.is_actionable(snapshot):
        return False
    digest = heartbeat_snapshot.canonical_hash(snapshot)
    unchanged = digest == row["snapshot_hash"]
    # The stall test comes *before* the skip is recorded. Recording it first
    # would move `next_due_at` into the future, and the post that this very
    # branch is deciding to allow would then be refused as not yet due — the
    # alarm could never fire.
    if (
        unchanged
        and row["quiet_wakes"] + 1 >= heartbeat_snapshot.STALL_AFTER_QUIET
        and heartbeat_snapshot.stalled_lines(snapshot)
    ):
        return False
    # Changed but not actionable, or unchanged and not yet stalled: record the
    # digest so an identical state stays quiet, and spend no turn.
    heartbeat_wake.record_quiet_skip(runtime.db, _next_due(row, now), digest)
    return True


def _next_due(row: dict, now: float) -> float:
    """The next boundary, catching up rather than owing every missed one."""
    due = row["next_due_at"] + row["interval_seconds"]
    return due if due > now else now + row["interval_seconds"]


async def tick(runtime, *, now: float | None = None) -> int | None:
    """One pass: settle what arrived, retry what is owed, or post what is due.

    Returns a newly posted message id, or None. A reminder that was committed
    but never delivered — a crash between the transaction and the paste — is
    retried here rather than replaced, because the row already names the exact
    message that is owed.
    """
    moment = time.time() if now is None else now
    row = heartbeat_wake.settle_delivered(runtime.db, now=moment)
    if row is None or not row["enabled"]:
        return None
    owner = deliverable_owner(runtime, row)
    if owner is None:
        return None
    if row["pending_message_id"] is not None:
        await _deliver_claimed(
            runtime, owner["id"], row["generation"], row["pending_message_id"]
        )
        heartbeat_wake.settle_delivered(runtime.db, now=moment)
        return None
    if _stay_quiet(runtime, row, moment):
        return None
    snapshot = heartbeat_snapshot.build(
        runtime.db, row["conv_id"], row["since_id"], row["attachment_id"]
    )
    claimed = heartbeat_wake.post_due_reminder(
        runtime.db,
        moment,
        sender="system",
        snapshot=snapshot,
        snapshot_hash=heartbeat_snapshot.canonical_hash(snapshot),
        body_for=lambda pending, delta: heartbeat.wake_body(
            owner["name"], pending["goal"]
        ) + "\n" + heartbeat_snapshot.render(delta),
    )
    if claimed is None:
        return None
    posted, generation, _snapshot = claimed
    await runtime.broadcast(
        row["conv_id"], MessageEvent(message=MessageResponse.model_validate(posted))
    )
    await _deliver_claimed(runtime, owner["id"], generation, posted["id"])
    # Settle here as well as at the top of the next tick, so `status` is
    # truthful the moment a reminder has actually landed rather than for the
    # rest of the tick interval.
    heartbeat_wake.settle_delivered(runtime.db, now=moment)
    return posted["id"]


async def run(runtime, *, sleep=asyncio.sleep, clock=time.time) -> None:
    """Tick until cancelled. One failing pass must not end the monitor."""
    while True:
        try:
            await tick(runtime, now=clock())
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("lead heartbeat tick failed; continuing")
        await sleep(TICK_SECONDS)
