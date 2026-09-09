"""`@!name` — stop what you are doing and read this.

An ordinary mention waits for a turn boundary, which is the right default:
most harnesses discard or defer input mid-turn, and interrupting one costs
whatever tool was in flight. `@!name` is the deliberate exception, and every
constraint here exists because it is expensive.

**Humans only.** An agent's reply wakes other agents, so letting agents write
the bang would let a busy room cancel its own work in a loop. Antigravity's
transcripts on this machine already contain six consecutive interrupts, each
answered by an empty planner response and then interrupted again. An
agent-written `@!name` is therefore delivered as a plain mention.

**One pending interruption per process.** A second bang aimed at a process
whose interrupt has not yet resolved is dropped rather than stacked.

**The message is never lost.** The interrupt is best-effort; delivery is not.
Whether the interrupt is confirmed, refused, or unsupported, the mention is
still delivered afterwards and the room is told what happened.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# `None` is a real runtime owner, so absence needs its own sentinel.
_MISSING = object()


@dataclass(frozen=True)
class InterruptOutcome:
    """What happened, in the words the room will be told."""

    attempted: bool
    confirmed: bool
    # Always populated: interrupting is destructive, so every outcome — taken,
    # refused, unsupported, or unconfirmed — is a record the room gets to see.
    notice: str


@dataclass
class PendingInterrupts:
    """Which processes have an interrupt in flight.

    Keyed by attachment id *and* runtime owner: a replaced activation is a
    different process, and holding a stale flag against it would silently
    refuse the first interrupt of the new one.
    """

    owners: dict[str, str | None] = field(default_factory=dict)

    def claim(self, attachment_id: str, runtime_owner: str | None) -> bool:
        if attachment_id in self.owners and self.owners[attachment_id] == runtime_owner:
            return False
        self.owners[attachment_id] = runtime_owner
        return True

    def release(self, attachment_id: str, runtime_owner: str | None) -> None:
        """Give up only the claim this caller made.

        A slow interrupt can outlive the activation that started it. By the
        time it returns, a replacement may hold the slot, and popping blindly
        would hand a *newer* process a free pass to a second concurrent
        interrupt — the one thing the slot exists to prevent.
        """
        if self.owners.get(attachment_id, _MISSING) == runtime_owner:
            self.owners.pop(attachment_id, None)


PENDING = PendingInterrupts()


def supports_interrupt(adapter: object) -> bool:
    """Whether this adapter publishes a supported way to stop a running turn.

    Absence means no. An adapter that cannot prove it interrupted must not be
    hammered with keystrokes on the chance that one lands.
    """
    return callable(getattr(adapter, "interrupt", None))


async def interrupt_for(
    attachment: dict,
    adapter: object,
    *,
    pending: PendingInterrupts | None = None,
) -> InterruptOutcome:
    """Try to stop this process's current turn before its message arrives."""
    pending = PENDING if pending is None else pending
    name = attachment["name"]
    if not supports_interrupt(adapter):
        return InterruptOutcome(False, False, (
            f"⚠ @{name} cannot be interrupted — the {attachment['adapter']} adapter has no "
            "supported interrupt, so the message was delivered as an ordinary mention"
        ))
    owner = attachment.get("runtime_owner")
    if not pending.claim(attachment["id"], owner):
        return InterruptOutcome(False, False, (
            f"⚠ @{name} already has an interruption in flight — this message was delivered "
            "without a second one"
        ))
    try:
        confirmed = bool(await adapter.interrupt())
    except Exception:
        logger.exception("interrupt of @%s failed", name)
        return InterruptOutcome(True, False, (
            f"⚠ @{name} could not be interrupted; the message was delivered as an ordinary "
            "mention and its turn was left running"
        ))
    finally:
        pending.release(attachment["id"], owner)
    if confirmed:
        return InterruptOutcome(True, True, f"☏ @{name} was interrupted to take this message")
    return InterruptOutcome(True, False, (
        f"⚠ @{name} did not confirm the interruption — the message was delivered, but its "
        "turn may still be running"
    ))
