"""The accepted hand-off: POST accept puts returned work on the line's own branch.

A child's final work used to sit on a detached ref or a side branch while the
line's own branch stayed at an early commit, and a parent relaying "the SHA
from the report" pushed the wrong commit once. The hand-off is mechanical now:
a captain of the parent — or the line's own captain, marking hand-off — names
a SHA, and the server verifies it exists, verifies the line's branch can
fast-forward to it, moves the branch, and records it on the line for the ☏
checkout line and the staffing board. Nothing is pushed and no history is
rewritten: a SHA the branch cannot fast-forward to is refused. The hand-off
is the SHA on the line's branch; nothing else counts.
"""

from __future__ import annotations

import os
import re
import subprocess

from fastapi import HTTPException, Request

from .auth_guard import request_principal
from .hierarchy_contracts import AcceptIn, AcceptResponse
from .line_worktree import WORKTREES_DIR, _git, line_cwd, repo_root
from .machine_scope import deny_unless

_SHA = re.compile(r"[0-9a-f]{4,64}")
_MARKER = f"/{WORKTREES_DIR}/"


class AcceptError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _locate(cwd: str) -> tuple[str | None, str | None]:
    """The repository root and the line's worktree, when that still exists.

    A placed line is recognised by its worktree path, so a worktree removed
    after an archive still names both sides; a line in a shared checkout is
    its own worktree.
    """
    cwd = (cwd or "").rstrip("/")
    if _MARKER in cwd:
        root = cwd.split(_MARKER, 1)[0]
        if not os.path.isdir(root):
            return None, None
        return root, cwd if os.path.isdir(cwd) else None
    if not cwd or not os.path.isdir(cwd):
        return None, None
    return repo_root(cwd), cwd


def _branch_name(cwd: str) -> str:
    """The one branch the hand-off lands on: ``line/<worktree name>``, or the
    branch a shared checkout is on right now."""
    if _MARKER in cwd:
        return f"line/{os.path.basename(cwd)}"
    done = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)
    branch = done.stdout.strip() if done.returncode == 0 else ""
    if not branch or branch == "HEAD":
        raise AcceptError(409, "this checkout is on a detached HEAD; there is no line branch to move")
    return branch


def _rev(cwd: str, *args: str) -> str | None:
    try:
        done = _git(*args, cwd=cwd)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None


def _git_failure(done, fallback: str) -> AcceptError:
    lines = [line for line in (done.stderr or "").splitlines() if line.strip()]
    return AcceptError(409, f"{fallback}: {lines[-1]}" if lines else fallback)


def _move_branch(root: str, worktree: str | None, branch: str, full: str) -> None:
    """Fast-forward in the worktree when it holds the branch; move the ref otherwise."""
    if worktree and os.path.isdir(worktree):
        if _rev(worktree, "rev-parse", "--abbrev-ref", "HEAD") == branch:
            done = _git("merge", "--ff-only", "--quiet", full, cwd=worktree)
            if done.returncode != 0:
                raise _git_failure(done, f"cannot fast-forward {branch} in the worktree")
            return
    done = _git("branch", "--force", branch, full, cwd=root)
    if done.returncode != 0:
        raise _git_failure(done, f"cannot move {branch} to the accepted SHA")


def accept_sha(db, conv_id: str, sha: str) -> dict:
    """Verify the SHA, fast-forward the line's branch to it, and record it.

    Returns ``{"branch": name, "sha": full, "moved": bool}`` — ``moved`` is
    False when the branch already pointed at the SHA, so re-accepting is a
    clean no-op that leaves the record in place.
    """
    conv = db.get_conversation(conv_id)
    if conv is None:
        raise AcceptError(404, "line not found")
    cwd = line_cwd(db, conv_id) or ""
    root, worktree = _locate(cwd)
    if root is None:
        raise AcceptError(409, "this line does not work inside a git repository")
    name = sha.strip().lower()
    if not _SHA.fullmatch(name):
        raise AcceptError(400, "pass the commit SHA (hex) to accept")
    probe = worktree if worktree and os.path.isdir(worktree) else root
    full = _rev(probe, "rev-parse", "--verify", "--quiet", f"{name}^{{commit}}")
    if full is None:
        raise AcceptError(400, f"no commit {name} in this repository")
    branch = _branch_name(cwd)
    head = _rev(root, "rev-parse", "--verify", "--quiet", branch)
    if head is None:
        raise AcceptError(409, f"no branch {branch} to accept onto")
    base = _rev(root, "merge-base", branch, full)
    moved = head != full
    if moved:
        if base is None:
            raise AcceptError(409, f"{name} shares no history with {branch}")
        if base != head:
            ahead = _rev(root, "rev-list", "--count", f"{full}..{branch}")
            count = f" has {ahead} commit(s)" if ahead else ""
            raise AcceptError(
                409,
                f"accepting only fast-forwards: {branch}{count} the accepted SHA does not include",
            )
        _move_branch(root, worktree, branch, full)
    db._exec("UPDATE conversations SET accepted_sha=? WHERE id=?", (full, conv_id))
    return {"branch": branch, "sha": full, "moved": moved}


def accepted_note(db, conv_id: str) -> str:
    """Rides the ☏ checkout line: the recorded hand-off, so nobody plans from a stale belief."""
    conv = db.get_conversation(conv_id) or {}
    sha = conv.get("accepted_sha") or ""
    return f" — accepted hand-off: {sha[:12]}" if sha else ""


def register_accept_route(app, runtime) -> None:
    @app.post("/api/conversations/{conv_id}/accept", response_model=AcceptResponse)
    async def accept(request: Request, conv_id: str, body: AcceptIn):
        db = runtime.db
        principal = request_principal(request)
        deny_unless(db, principal, conv_id, "accept")
        try:
            done = accept_sha(db, conv_id, body.sha)
        except AcceptError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc
        state = "already at" if not done["moved"] else "moved to"
        await runtime.post_message(
            conv_id, "system", "system",
            f"☏ hand-off accepted by @{principal.name}: {done['branch']} {state} "
            f"{done['sha'][:12]} — the hand-off is the SHA on the line's branch",
        )
        return AcceptResponse(
            conv_id=conv_id, branch=done["branch"], sha=done["sha"], moved=done["moved"]
        )
