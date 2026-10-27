"""Retiring a line: every blocker in one answer, and the explicit discard path.

Retirement used to refuse one thing at a time — live processes, then an
uncleared goal, then unmerged commits, then uncommitted changes — so a captain
fixed one and learned the next on the following round trip. This collects them
all, so one response names everything standing between the caller and a clean
retirement. ``discard`` is the one explicit relief: a merged branch's dirty
worktree may be thrown away, and only a merged one.
"""

from __future__ import annotations

from .hierarchy import child_ids, descendants
from .worktree_lifecycle import worktree_state
from .retirement_worktree import check_line

LIVE = ("starting", "running")
# The one flag a caller passes to clear each guard. A refusal names every flag
# its blockers need at once, so a captain fixes a whole retirement in one pass.
FLAG_FOR = {
    "live_processes": "stop_processes",
    "goal_not_cleared": "clear_goal",
    "child_lines": "include_children",
    "unmerged_commits": "force_discard",
    "uncommitted_changes": "discard",
    "nested_repositories": "force_discard",
}


def _blocker(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def required_flags(blockers: list[dict]) -> list[str]:
    """Every flag this refusal would accept, from every blocker, in one answer."""
    return sorted({FLAG_FOR[blocker["code"]] for blocker in blockers
                   if blocker["code"] in FLAG_FOR})


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
    check_line(db, conv)
    blockers: list[dict] = []
    live = [att for att in db.list_attachments(conv_id) if att["status"] in LIVE]
    if strict and live and not ignore_live_processes:
        names = ", ".join("@" + att["name"] for att in live)
        blockers.append(_blocker(
            "live_processes",
            f"live processes: this line still has live processes ({names}); stop them first "
            f"with POST /api/conversations/{{id}}/attachments/close, or pass "
            f"stop_processes=true to stop them as part of this retirement",
        ))
    if strict and conv.get("goal"):
        blockers.append(_blocker(
            "goal_not_cleared",
            "goal not cleared: this line's goal is not cleared; clear it before retiring the "
            "line, or pass clear_goal=true to clear it as part of this retirement",
        ))
    if not include_children and child_ids(db, conv_id, include_archived=False):
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
                "must merge first — or the tree's root captain passes force_discard=true with "
                "a retirement preview_token",
            ))
        waives_dirty = discard and state["merged"]
        if strict and state["nested"] and not discard:
            blockers.append(_blocker(
                "nested_repositories",
                f"nested repositories: the worktree contains {', '.join(state['nested'])}, separate "
                "git repositories partyline never deletes; move or delete them by hand. With "
                "discard=true the line is archived and the worktree is kept; a root captain's "
                "force_discard=true keeps it too",
            ))
        elif strict and not state["clean"] and not waives_dirty:
            blockers.append(_blocker(
                "uncommitted_changes",
                "uncommitted changes: the worktree is dirty; commit them, or pass discard=true "
                "(allowed only for an already-merged branch); a root captain may instead pass "
                "force_discard=true with a retirement preview_token",
            ))
    if include_children:
        for line_id in descendants(db, conv_id, include_archived=False):
            for item in archive_blockers(
                db, line_id, include_children=False, discard=discard, strict=strict,
                ignore_live_processes=ignore_live_processes,
            ):
                if item["code"] != "child_lines":
                    blockers.append({**item, "message": f"{line_id}: {item['message']}"})
    return blockers
