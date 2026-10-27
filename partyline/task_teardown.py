"""Ending a task's workspace: keep its commits, remove only what git can remove without loss.

A task's commits live as objects in each real clone, with the branch tip in the
process's private refs mirror. Before anything goes, each tip is copied onto the
task's own `line/<slug>` branch in its clone (or, when that branch moved on its own,
held by a hidden ref). Each nested worktree is then removed through its clone with
no `--force`, so a dirty one is kept and named; the branches stay.
"""

from __future__ import annotations

import os
import subprocess

from .line_worktree import WORKTREES_DIR, _git, rev
from .nested_repositories import nested_repositories
from .retirement_worktree import remove_directory
from .task_workspaces import GUIDES, anchor, tip, workspaces


def _descends(repo: str, older: str, newer: str) -> bool:
    return _git("merge-base", "--is-ancestor", older, newer, cwd=repo).returncode == 0


def preserve(db, conv_id: str) -> None:
    """Put every workspace tip on its task branch in the real clone, or hold it by a hidden ref."""
    anchor(db, conv_id)
    for item in workspaces(db, conv_id):
        head = tip(item, conv_id)
        branch = f"refs/heads/{item['branch']}"
        real = rev(item["repository"], "rev-parse", "--verify", "--quiet", branch)
        if head and real and head != real and _descends(item["repository"], real, head):
            _git("update-ref", branch, head, real, cwd=item["repository"])


def remove_nested(db, conv_id: str, cwd: str) -> list[str]:
    """Remove each nested worktree (not the task folder's own); the paths that stayed."""
    kept = []
    for item in reversed(workspaces(db, conv_id)):
        path = item["path"]
        if os.path.realpath(path) == os.path.realpath(cwd) or not os.path.isdir(path):
            continue
        try:
            done = _git("status", "--porcelain", cwd=path)
            if done.returncode or done.stdout.strip() or nested_repositories(path):
                kept.append(path)
                continue
            remove_directory(path, item["repository"])
            _git("worktree", "prune", cwd=item["repository"])
        except (OSError, subprocess.SubprocessError):
            kept.append(path)
            continue
        if os.path.exists(path):
            kept.append(path)
    return kept


def remove_plain_folder(db, conv_id: str, cwd: str) -> None:
    """The task folder of a root that is no repository: the guide links, then the empty folder."""
    if os.path.isdir(os.path.join(cwd, ".git")) or os.path.isfile(os.path.join(cwd, ".git")):
        return
    for guide in GUIDES:
        link = os.path.join(cwd, guide)
        if os.path.islink(link):
            os.unlink(link)
    try:
        os.rmdir(cwd)
        os.rmdir(os.path.dirname(cwd))  # only when no other task folder remains
    except OSError:
        pass


def teardown(db, conv_id: str, cwd: str) -> list[str]:
    """Preserve, then remove the nested worktrees and a plain task folder; what stayed."""
    if not workspaces(db, conv_id) or WORKTREES_DIR not in cwd:
        return []
    preserve(db, conv_id)
    kept = remove_nested(db, conv_id, cwd)
    if not kept:
        remove_plain_folder(db, conv_id, cwd)
    return kept
