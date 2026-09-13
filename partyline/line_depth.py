"""How deep a line sits in its tree, and what that permits.

Every captain used to receive the same pack — "spin up a sub-line with a
captain" — so a child captain spun up a grandchild, whose captain would have
spun up another. Depth is the ancestor count: a root line is depth 0. A
machine may create children only above ``MAX_CAPTAIN_DEPTH``; a line at the
cap is a leaf, whose captain staffs workers on the line itself. People are
never boxed by the cap: the recursion is model-driven.

Work goes down, not sideways. A captain whose line already has a child may
not attach workers to its own line: the root captain who cannot staff a
child (or does not check why) otherwise hands the job to a sibling on the
root line, in the same checkout the child lines are already editing.
"""

from __future__ import annotations

from .hierarchy import ancestors, child_ids

MAX_CAPTAIN_DEPTH = 2


def depth(db, conv_id: str) -> int:
    return len(ancestors(db, conv_id))


def may_create_children(db, conv_id: str) -> bool:
    return depth(db, conv_id) < MAX_CAPTAIN_DEPTH


def sideways_attach_reason(db, conv_id: str) -> str | None:
    """Why a machine may not attach a process to this line, or None."""
    if child_ids(db, conv_id):
        return ("this line already has child lines; work goes down, not sideways — "
                "attach the process to the child line that owns the slice")
    return None
