"""The task worktrees a fenced process may commit in, beyond its own cwd's git directory.

A task folder can hold a worktree of several clones. Each needs the same git
binds as a single worktree line (private refs mirror, shared objects, read-only
config and hooks), and its real clone is protected from the task's processes.
Only rows recorded for this attachment's own line count, and only a worktree
that really lives under its cwd and belongs to the recorded clone.
"""

from __future__ import annotations

import os

from . import git_fence


def checkouts(att: dict) -> list[str]:
    """Recorded nested worktrees under the attachment's cwd, canonical and verified."""
    cwd = os.path.realpath(att.get("cwd") or "")
    found = []
    for row in att.get("task_workspaces") or []:
        path = row.get("path")
        if (row.get("conv_id") != att.get("conv_id") or not isinstance(path, str)
                or os.path.realpath(path) != path or path == cwd
                or not path.startswith(cwd + os.sep) or os.path.islink(path)):
            continue
        gitdir = git_fence._worktree_gitdir(path)
        clone = os.path.realpath(row.get("repository") or "")
        if gitdir and os.path.realpath(git_fence.common_gitdir(gitdir)) == os.path.join(clone, ".git"):
            found.append(path)
    return found


def load(db, att: dict) -> None:
    """Set the attachment's protected roots; a task's real clones join them, so its processes
    reach a clone only through their worktree."""
    from .fence_protect import protected_repo_roots
    from .task_workspaces import workspaces

    att["task_workspaces"] = [dict(row, conv_id=att["conv_id"]) for row in workspaces(db, att["conv_id"])]
    att["protected_roots"] = sorted({*protected_repo_roots(db),
                                    *(row["repository"] for row in att["task_workspaces"])})
