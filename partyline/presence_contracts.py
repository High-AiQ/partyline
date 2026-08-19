"""Named contracts for who is mid-turn.

These live apart from ``contracts.py`` for the same reason the image models
do: that file sits a handful of lines under the 300-line production cap, and
the presence models do not fit beside it.
"""

from typing import Literal

from pydantic import BaseModel

# ``quiet`` is reserved, not emitted. No bundled CLI has trustworthy output
# timing without a turn-end receipt, so emitting it today would be a guess.
PresencePhase = Literal["idle", "working", "speaking", "quiet"]
# Claude and Grok provide process-scoped harness receipts; every other bundled
# adapter is ``none`` and never clears itself without an authoritative signal.
PresenceCompletion = Literal["receipt", "none"]


class PresenceState(BaseModel):
    """One attachment's activity at snapshot time, including idle tombstones."""

    id: str
    phase: PresencePhase
    completion: PresenceCompletion = "none"
    since: float
    turn: int
    revision: int


class WorkingEvent(BaseModel):
    """A server-owned activity transition with its legacy boolean."""

    type: Literal["working"] = "working"
    attachment_id: str
    working: bool
    phase: PresencePhase = "idle"
    completion: PresenceCompletion = "none"
    since: float = 0
    turn: int = 0
    revision: int = 0
