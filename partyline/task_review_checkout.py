"""One stable review checkout per task, moved in place to each round's SHA.

A reviewer's CLI session is tied to the folder it started in, so a task's
reviewer keeps one folder, ``<repo>/.review/task-<line id>``, for every round.
Moving it to a new SHA discards the previous round's files, ignored ones
included, so nothing from round 1 can be read as part of round 2.
"""

from __future__ import annotations

import os
import shutil
import time

from .line_worktree import REVIEW_DIR, _exclude, _git, rev
from .review_worktrees import _SHA, ReviewError, _registered, _repo_of


def task_review_path(root: str, conv_id: str) -> str:
    return os.path.realpath(os.path.join(root, REVIEW_DIR, f"task-{conv_id}"))


def _run(path: str, *args: str) -> None:
    done = _git(*args, cwd=path)
    if done.returncode != 0:
        detail = (done.stderr or "").strip().splitlines()
        raise ReviewError(409, f"cannot move the task review checkout: "
                               f"{detail[-1] if detail else 'git failed'}")


def move_task_review_worktree(db, conv_id: str, sha: str) -> dict:
    """Check the exact SHA out in the task's one review checkout and record it."""
    root = _repo_of(db, conv_id)
    name = (sha or "").strip().lower()
    if not _SHA.fullmatch(name):
        raise ReviewError(400, "pass the commit SHA (hex) to review")
    full = rev(root, "rev-parse", "--verify", "--quiet", f"{name}^{{commit}}")
    if full is None:
        raise ReviewError(400, f"no commit {name} in this repository")
    path = task_review_path(root, conv_id)
    if os.path.isdir(path) and not _registered(root, path):
        shutil.rmtree(path, ignore_errors=True)  # not git's worktree: partyline's to replace
    if os.path.isdir(path):
        _run(path, "checkout", "--force", "--detach", full)
        _run(path, "clean", "-ffdx")
    else:
        os.makedirs(os.path.join(root, REVIEW_DIR), exist_ok=True)
        _exclude(root, REVIEW_DIR)
        _git("worktree", "prune", cwd=root)
        _run(root, "worktree", "add", "--detach", path, full)
    created_at = time.time()
    db._exec(
        "INSERT INTO review_worktrees(conv_id,sha,path,created_at) VALUES(?,?,?,?) "
        "ON CONFLICT(path) DO UPDATE SET conv_id=excluded.conv_id, sha=excluded.sha, "
        "created_at=excluded.created_at",
        (conv_id, full, path, created_at),
    )
    return {"conv_id": conv_id, "sha": full, "path": path, "created_at": created_at}
