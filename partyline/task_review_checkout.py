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
from .review_scope import (
    ReviewError, accepted_repositories, branch_candidates, describe, on_line_branch,
    resolve_repository)
from .review_worktrees import _SHA, _registered


def task_review_path(root: str, conv_id: str) -> str:
    return os.path.realpath(os.path.join(root, REVIEW_DIR, f"task-{conv_id}"))


def _run(path: str, *args: str) -> None:
    done = _git(*args, cwd=path)
    if done.returncode != 0:
        detail = (done.stderr or "").strip().splitlines()
        raise ReviewError(409, f"cannot move the task review checkout: "
                               f"{detail[-1] if detail else 'git failed'}")


def _commit_in(root: str, name: str) -> str | None:
    return rev(root, "rev-parse", "--verify", "--quiet", f"{name}^{{commit}}")


def resolve_commit(db, conv_id: str, repository: str, sha: str) -> tuple[str, str]:
    """``(repository root, full sha)`` for one entry, or a ReviewError.

    A SHA with no repository is looked up in the line's own repository first,
    then in every other repository accepted for the line: an implementer that
    committed in a sibling still gets its commit reviewed, and an ambiguous
    SHA is refused rather than guessed.
    """
    name = (sha or "").strip().lower()
    if not _SHA.fullmatch(name):
        raise ReviewError(400, "pass the commit SHA (hex) to review")
    root = resolve_repository(db, conv_id, repository, name)[0]
    full = _commit_in(root, name)
    if full is not None:
        return root, full
    if repository and repository.strip():
        raise ReviewError(400, f"no commit {name} in {root}; repositories accepted for this "
                               f"line: {describe(accepted_repositories(db, conv_id))}")
    accepted = accepted_repositories(db, conv_id)
    searched = [*accepted, *[item for item in branch_candidates(db, conv_id, accepted)
                             if on_line_branch(db, conv_id, item[0], name)]]
    hits = [(other, found) for other, _line in searched
            if os.path.realpath(other) != os.path.realpath(root)
            and (found := _commit_in(other, name)) is not None]
    if len(hits) == 1:
        return hits[0]
    if hits:
        where = ', '.join(found for found, _full in hits)
        raise ReviewError(409, f"commit {name} exists in several repositories ({where}); "
                               "pass repositories=[{repository, sha}] to say which")
    raise ReviewError(400, f"no commit {name} in the line's repository {root} nor in any other "
                           f"repository accepted for this line ({describe(accepted)}); commit on this "
                           "line's branch, or ask for a write grant on the repository you committed in "
                           "and pass repositories=[{repository, sha}]")


def _move(db, conv_id: str, root: str, full: str) -> dict:
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
    db._exec(
        "INSERT INTO review_worktrees(conv_id,sha,path,created_at) VALUES(?,?,?,?) "
        "ON CONFLICT(path) DO UPDATE SET conv_id=excluded.conv_id, sha=excluded.sha, "
        "created_at=excluded.created_at",
        (conv_id, full, path, time.time()),
    )
    return {"repository": root, "sha": full, "path": path}


def move_task_review_worktrees(db, conv_id: str, entries: list[tuple[str, str]],
                               primary: str | None = None) -> list[dict]:
    """Move the task's checkout in each ``(repository, sha)`` entry to its SHA.

    Everything is resolved before anything moves. The first result is the
    primary entry, whose checkout is the reviewer's folder; a task that
    already has a primary repository keeps it first, so that folder never
    changes between rounds.
    """
    found = [resolve_commit(db, conv_id, repository, sha) for repository, sha in entries]
    roots = [os.path.realpath(root) for root, _full in found]
    if len(set(roots)) != len(roots):
        raise ReviewError(422, "each repository may appear once in a review")
    if primary:
        if os.path.realpath(primary) not in roots:
            raise ReviewError(
                409, f"a review must keep the task's primary repository {primary}; "
                     "pass repositories again, including it")
        found.sort(key=lambda item: os.path.realpath(item[0]) != os.path.realpath(primary))
    return [_move(db, conv_id, root, full) for root, full in found]
