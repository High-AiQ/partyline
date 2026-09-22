"""Retiring a line: every blocker in one answer, and the explicit discard path.

Retirement used to refuse one thing at a time — live processes, then an
uncleared goal, then unmerged commits, then uncommitted changes — so a captain
fixed one and learned the next on the following round trip. This collects them
all, so one response names everything standing between the caller and a clean
retirement. ``discard`` is the one explicit relief: a merged branch's dirty
worktree may be thrown away, and only a merged one.
"""

from __future__ import annotations

from .hierarchy import child_ids
from .worktree_lifecycle import worktree_state

LIVE = ("starting", "running")


def _blocker(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def archive_blockers(
    db, conv_id: str, *, include_children: bool, discard: bool, strict: bool,
    ignore_live_processes: bool = False,
) -> list[dict]:
    """Every reason this retirement would be refused, in one list.

    ``strict`` is a machine captain: it is held to live processes and an
    uncleared goal as well, and to the SAFE test for both unmerged commits and
    uncommitted changes. A person is held only to child lines — and to the
    explicit ``discard``, which is refused outright when the branch is not
    merged, because those commits exist nowhere else. ``ignore_live_processes``
    is only for an archive preflight that has already checked those processes
    and will stop them atomically after every other blocker clears.
    """
    conv = db.get_conversation(conv_id) or {}
    blockers: list[dict] = []
    live = [att for att in db.list_attachments(conv_id) if att["status"] in LIVE]
    if strict and live and not ignore_live_processes:
        names = ", ".join("@" + att["name"] for att in live)
        blockers.append(_blocker(
            "live_processes",
            f"live processes: this line still has live processes ({names}); stop them first "
            f"with POST /api/conversations/{{id}}/attachments/close",
        ))
    if strict and conv.get("goal"):
        blockers.append(_blocker(
            "goal_not_cleared",
            "goal not cleared: this line's goal is not cleared; clear it before retiring the line",
        ))
    if not include_children and child_ids(db, conv_id):
        blockers.append(_blocker(
            "child_lines",
            "child lines: unlink or archive child lines first, or pass include_children=true",
        ))
    state = worktree_state(db, conv)
    if state is not None:
        if not state["merged"] and (strict or discard):
            blockers.append(_blocker(
                "unmerged_commits",
                "unmerged commits: this line's branch or worktree HEAD has commits not "
                "reachable from the parent branch or the repository default; merge it, and "
                "never discard it. A person may retire from the UI, while a machine captain "
                "must merge first",
            ))
        waives_dirty = discard and state["merged"]
        if strict and not state["clean"] and not waives_dirty:
            blockers.append(_blocker(
                "uncommitted_changes",
                "uncommitted changes: the worktree is dirty; commit them, or pass discard=true "
                "(allowed only for an already-merged branch)",
            ))
    return blockers
