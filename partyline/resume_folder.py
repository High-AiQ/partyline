"""A resumed process needs its working folder; bring a task reviewer's back or say what to do."""

from __future__ import annotations

import os

from fastapi import HTTPException

from .orchestrator_store import attachment_task
from .review_scope import ReviewError
from .task_review_checkout import move_task_review_worktrees


def _recreate_review_checkout(db, att: dict, row: dict) -> None:
    """Rebuild the task's disposable review checkout at the SHAs of its last round."""
    entries = [(item["repository"], item["sha"]) for item in row.get("repositories") or []]
    if not entries and row.get("sha"):
        entries = [("", row["sha"])]
    primary = entries[0][0] if entries else None
    try:
        move_task_review_worktrees(db, att["conv_id"], entries, primary or None)
    except ReviewError as exc:
        raise HTTPException(
            409, f"@{att['name']}'s review checkout {att['cwd']} was removed and could not be "
                 f"recreated: {exc.detail}; call request_review again to restage it") from exc


def ensure_resume_folder(db, att: dict) -> None:
    """Recreate a removed review checkout, or fail with an actionable message."""
    cwd = att.get("cwd")
    if not cwd or os.path.isdir(cwd):
        return
    row = attachment_task(db, att["id"])
    if (row and row["reviewer_id"] == att["id"] and row.get("review_worktree")
            and os.path.realpath(row["review_worktree"]) == os.path.realpath(cwd)):
        _recreate_review_checkout(db, att, row)
        if os.path.isdir(cwd):
            return
    raise HTTPException(
        409, f"@{att['name']}'s working folder {cwd} no longer exists; restore it, or detach "
             "this process and attach a fresh one in a folder that does")
