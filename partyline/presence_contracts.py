"""Named contracts for who is mid-turn.

These live apart from ``contracts.py`` for the same reason the image models
do: that file sits a handful of lines under the 300-line production cap, and
the presence models do not fit beside it. ``contracts.py`` imports from here
so the event union and the conversation snapshot stay in one place.
"""

from typing import Literal

from pydantic import BaseModel

# ``quiet`` is reserved, not emitted. @grok's adapter survey found no bundled
# CLI with trustworthy output timing but no turn-end receipt, so a server that
# said "quiet" would be guessing — and a guessed ending is the bug this whole
# area exists to remove. It stays on the wire so a client written today
# renders it correctly if a future adapter ever earns it.
PresencePhase = Literal["idle", "working", "speaking", "quiet"]
# ``receipt``: the harness reports its own turn boundaries (claude, grok).
# ``none``: it does not, so the server never clears the badge on its own and
# the client lowers its confidence from ``since`` instead.
PresenceCompletion = Literal["receipt", "none"]


class PresenceState(BaseModel):
    """One attachment's activity at snapshot time.

    Finished turns appear here too, as ``idle``, carrying the revision that
    closed them: a client buffering events while its snapshot is in flight
    cannot order a held event against an attachment the snapshot omits.
    """

    id: str
    phase: PresencePhase
    completion: PresenceCompletion = "none"
    since: float
    turn: int
    revision: int


class WorkingEvent(BaseModel):
    """A process began or finished a turn. Only the server ever sends this.

    ``working`` is the original boolean and stays truthful for clients that
    predate the phases: true for ``working`` and ``speaking``, false
    otherwise. ``revision`` rises on every announcement for one attachment,
    which is what lets a client discard an event older than the snapshot it
    already applied — a turn number cannot order transitions *inside* a turn,
    and working → speaking → working is exactly that.
    """

    type: Literal["working"] = "working"
    attachment_id: str
    working: bool
    phase: PresencePhase = "idle"
    completion: PresenceCompletion = "none"
    since: float = 0
    turn: int = 0
    revision: int = 0
