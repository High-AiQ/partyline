"""Bounded read-only Git visibility for every repository in a task workspace."""

from __future__ import annotations

import os

from .git_fence import mirror_branch_ref
from .line_worktree import rev
from .task_workspaces import workspaces

SUBJECT_LIMIT = 120
SUBJECT_COUNT = 5


def _subject(subject: str) -> str:
    return subject if len(subject) <= SUBJECT_LIMIT else subject[:SUBJECT_LIMIT - 1] + "…"


def _unaccepted(repository: str, mirror_tip: str | None, host_tip: str | None) -> tuple[int, list[str]]:
    """Commits reachable from the mirror tip but not the real task branch."""
    if mirror_tip is None or mirror_tip == host_tip:
        return 0, []
    revision = f"{host_tip}..{mirror_tip}" if host_tip else mirror_tip
    count = rev(repository, "rev-list", "--count", revision)
    listed = rev(repository, "log", f"--max-count={SUBJECT_COUNT}", "--format=%s", revision)
    return int(count or 0), [_subject(item) for item in (listed or "").splitlines()]


def workspace_visibility(db, task_row: dict) -> list[dict]:
    """Describe real and fenced tips without changing refs, worktrees, or the database."""
    conv_id = task_row["conv_id"]
    accepted = {}
    if task_row.get("status") in ("approved", "done"):
        accepted = {os.path.realpath(item["repository"]): item["sha"]
                    for item in task_row.get("repositories") or [] if item.get("repository")}
    result = []
    for workspace in workspaces(db, conv_id):
        if task_row.get("status") == "done" and not os.path.isdir(workspace["path"]):
            continue
        repository = workspace["repository"]
        branch = workspace["branch"]
        fenced_tip = mirror_branch_ref(workspace["path"], conv_id, branch)
        host_tip = rev(repository, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
        count, subjects = _unaccepted(repository, fenced_tip, host_tip)
        result.append({
            "repository": repository,
            "path": workspace["path"],
            "branch": branch,
            "mirror_tip": fenced_tip or host_tip,
            "host_tip": host_tip,
            "accepted_sha": accepted.get(os.path.realpath(repository)),
            "unaccepted_count": count,
            "unaccepted_subjects": subjects,
        })
    return result
