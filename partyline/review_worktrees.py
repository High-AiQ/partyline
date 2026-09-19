"""Partyline-owned review worktrees: a disposable checkout per reviewed SHA.

Sub-captains used to run ``git worktree add /tmp/...`` for adversarial reviews
and nothing ever pruned them. A review gets a managed home instead: the
facility checks the exact SHA out at ``<repo>/.review/<full sha>``, detached,
records it on the line, and prunes every review worktree of a line when the
line retires or its SHA is accepted. Captains point reviewers at it instead of
teaching raw git; the SHAs themselves stay in the repository, so pruning a
review checkout can never lose the work that was reviewed.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import time

from fastapi import HTTPException, Request

from .auth_guard import request_principal
from .hierarchy_contracts import ReviewWorktreeIn, ReviewWorktreeOut
from .line_worktree import REVIEW_DIR, _exclude, _git, line_cwd, repo_and_worktree, rev
from .machine_scope import deny_unless

logger = logging.getLogger(__name__)

_SHA = re.compile(r"[0-9a-f]{4,64}")
_SHA_DIR = re.compile(r"[0-9a-f]{40}")


class ReviewError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _repo_of(db, conv_id: str) -> str:
    root, _worktree = repo_and_worktree(line_cwd(db, conv_id) or "")
    if root is None:
        raise ReviewError(409, "this line does not work inside a git repository")
    return root


def create_review_worktree(db, conv_id: str, sha: str) -> dict:
    """Check a SHA out at ``<repo>/.review/<sha>`` and record it on the line.

    Creating the same SHA twice returns the same worktree — a review that was
    interrupted picks its checkout back up instead of stacking copies.
    """
    conv = db.get_conversation(conv_id)
    if conv is None:
        raise ReviewError(404, "line not found")
    root = _repo_of(db, conv_id)
    name = (sha or "").strip().lower()
    if not _SHA.fullmatch(name):
        raise ReviewError(400, "pass the commit SHA (hex) to review")
    full = rev(root, "rev-parse", "--verify", "--quiet", f"{name}^{{commit}}")
    if full is None:
        raise ReviewError(400, f"no commit {name} in this repository")
    path = os.path.join(root, REVIEW_DIR, full)
    existing = db._exec(
        "SELECT sha, created_at FROM review_worktrees WHERE path=?", (path,)
    ).fetchone()
    if existing and os.path.isdir(path):
        return {"conv_id": conv_id, "sha": existing["sha"],
                "path": path, "created_at": existing["created_at"]}
    os.makedirs(os.path.join(root, REVIEW_DIR), exist_ok=True)
    _exclude(root, REVIEW_DIR)
    if not os.path.isdir(path):
        _git("worktree", "prune", cwd=root)  # a hand-deleted checkout leaves a stale registration
        done = _git("worktree", "add", "--detach", path, full, cwd=root)
        if done.returncode != 0:
            detail = (done.stderr or "").strip().splitlines()
            raise ReviewError(
                409, f"cannot create the review worktree: {detail[-1] if detail else 'git failed'}"
            )
    created_at = time.time()
    db._exec(
        "INSERT INTO review_worktrees(conv_id,sha,path,created_at) VALUES(?,?,?,?) "
        "ON CONFLICT(path) DO UPDATE SET conv_id=excluded.conv_id, sha=excluded.sha",
        (conv_id, full, path, created_at),
    )
    return {"conv_id": conv_id, "sha": full, "path": path, "created_at": created_at}


def list_review_worktrees(db, conv_id: str) -> list[dict]:
    return [
        dict(row) for row in db._exec(
            "SELECT conv_id, sha, path, created_at FROM review_worktrees "
            "WHERE conv_id=? ORDER BY created_at", (conv_id,),
        ).fetchall()
    ]


def remove_review_path(path: str) -> bool:
    """Delete one review worktree directory; False when git refused to let go.

    The checkout is disposable by contract — it holds no work of the line —
    so removal is forced and never asks about uncommitted scratch.
    """
    if not os.path.isdir(path):
        return True  # already gone by hand; only the record is stale
    marker = f"/{REVIEW_DIR}/"
    root = path.split(marker, 1)[0] if marker in path else None
    if root and os.path.isdir(root):
        done = _git("worktree", "remove", "--force", "--force", path, cwd=root)
        if done.returncode == 0:
            return True
        logger.warning("review worktree prune: git refused to remove %s", path)
        return False
    shutil.rmtree(path, ignore_errors=True)
    return not os.path.isdir(path)


def prune_review_worktrees(db, conv_id: str) -> dict:
    """Drop every review worktree recorded for the line. The SHAs stay in the repo.

    Returns ``{"removed": n, "kept": m}`` — ``kept`` counts worktrees git
    would not release (a locked checkout), whose records stay so a later
    prune or sweep can try again.
    """
    removed = kept = 0
    rows = db._exec(
        "SELECT path FROM review_worktrees WHERE conv_id=?", (conv_id,)
    ).fetchall()
    for row in rows:
        if remove_review_path(row["path"]):
            db._exec("DELETE FROM review_worktrees WHERE path=?", (row["path"],))
            removed += 1
        else:
            kept += 1
    return {"removed": removed, "kept": kept}


def sweep_review_worktrees(db, root: str) -> None:
    """Startup sweep for one repository's ``.review`` directory.

    A checkout whose line is gone, archived, or unrecorded is a leftover —
    the server died mid-review, or the record was lost — and partyline owns
    the directory. Only full-SHA directories are touched, so anything else a
    repository keeps in ``.review`` is never partyline's to delete.
    """
    directory = os.path.join(root, REVIEW_DIR)
    if not os.path.isdir(directory):
        return
    rows = {row["path"]: row["conv_id"] for row in
            db._exec("SELECT path, conv_id FROM review_worktrees").fetchall()}
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if not os.path.isdir(path) or not _SHA_DIR.fullmatch(name):
            continue
        conv = db.get_conversation(rows[path]) if path in rows else None
        if conv is not None and not conv.get("archived_at"):
            continue  # a live line is still reviewing here
        if remove_review_path(path):
            db._exec("DELETE FROM review_worktrees WHERE path=?", (path,))
            logger.info("review worktree sweep: removed %s", path)
    for path in rows:
        if not os.path.isdir(path):
            db._exec("DELETE FROM review_worktrees WHERE path=?", (path,))


def register_review_routes(app, runtime) -> None:
    @app.post(
        "/api/conversations/{conv_id}/review-worktrees",
        response_model=ReviewWorktreeOut, status_code=201,
    )
    async def create(request: Request, conv_id: str, body: ReviewWorktreeIn):
        db = runtime.db
        deny_unless(db, request_principal(request), conv_id, "read")
        try:
            done = create_review_worktree(db, conv_id, body.sha)
        except ReviewError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc
        await runtime.post_message(
            conv_id, "system", "system",
            f"☏ review worktree: {done['path']} — detached at {done['sha'][:12]} for the "
            "adversarial review; partyline prunes it when the line retires or the SHA is accepted",
        )
        return done

    @app.get(
        "/api/conversations/{conv_id}/review-worktrees",
        response_model=list[ReviewWorktreeOut],
    )
    def index(request: Request, conv_id: str):
        deny_unless(runtime.db, request_principal(request), conv_id, "read")
        return list_review_worktrees(runtime.db, conv_id)
