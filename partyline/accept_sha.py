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

from fastapi import HTTPException, Request

from .auth_guard import request_principal
from .hierarchy import descendants, parent_id_of
from .hierarchy_contracts import AcceptIn, AcceptResponse
from .line_worktree import WORKTREES_DIR, _git, line_cwd, repo_and_worktree, rev
from .machine_scope import deny_unless
from .review_worktrees import prune_accepted_review
from .worktree_lifecycle import _base_ref

_SHA = re.compile(r"[0-9a-f]{4,64}")


class AcceptError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _branch_name(cwd: str) -> str:
    """The one branch the hand-off lands on: the line worktree's ``line/<name>``.

    Accept is confined to placed line worktrees: a shared checkout's branch
    belongs to the person whose checkout it is, and partyline never
    fast-forwards it.
    """
    return f"line/{os.path.basename(cwd.rstrip('/'))}"


def _git_failure(done, fallback: str) -> AcceptError:
    lines = [line for line in (done.stderr or "").splitlines() if line.strip()]
    return AcceptError(409, f"{fallback}: {lines[-1]}" if lines else fallback)


def _move_branch(root: str, worktree: str | None, branch: str, full: str) -> None:
    """Fast-forward in the worktree when it holds the branch; move the ref otherwise."""
    if worktree and os.path.isdir(worktree):
        if rev(worktree, "rev-parse", "--abbrev-ref", "HEAD") == branch:
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
    root, worktree = repo_and_worktree(cwd)
    if root is None or f"/{WORKTREES_DIR}/" not in cwd:
        raise AcceptError(
            409,
            "accept is for a placed line worktree: this line works in a shared checkout, "
            "whose branch belongs to the person",
        )
    name = sha.strip().lower()
    if not _SHA.fullmatch(name):
        raise AcceptError(400, "pass the commit SHA (hex) to accept")
    probe = worktree if worktree and os.path.isdir(worktree) else root
    full = rev(probe, "rev-parse", "--verify", "--quiet", f"{name}^{{commit}}")
    if full is None:
        raise AcceptError(400, f"no commit {name} in this repository")
    branch = _branch_name(cwd)
    head = rev(root, "rev-parse", "--verify", "--quiet", branch)
    if head is None:
        raise AcceptError(409, f"no branch {branch} to accept onto")
    base = rev(root, "merge-base", branch, full)
    moved = head != full
    if moved:
        if base is None:
            raise AcceptError(409, f"{name} shares no history with {branch}")
        if base != head:
            ahead = rev(root, "rev-list", "--count", f"{full}..{branch}")
            count = f" has {ahead} commit(s)" if ahead else ""
            raise AcceptError(
                409,
                f"accepting only fast-forwards: {branch}{count} the accepted SHA does not include",
            )
        # Descent from the branch point: a branch still sitting exactly at its
        # merge-base with the parent carries no work of its own, so any other
        # SHA belongs to some other line's descent. Land the work on the
        # branch first — the hand-off is the SHA on the line's branch.
        parent_tip = _base_ref(line_cwd(db, parent_id_of(conv)) if parent_id_of(conv) else None)
        lineage = rev(root, "merge-base", branch, parent_tip) if parent_tip else None
        if lineage == head:
            raise AcceptError(
                409,
                f"{branch} has no commits of its own — it sits at its branch point with the "
                f"parent, so {name} is not this line's work; land the work on the branch first",
            )
        _move_branch(root, worktree, branch, full)
    db._exec("UPDATE conversations SET accepted_sha=? WHERE id=?", (full, conv_id))
    pruned = prune_accepted_review(db, conv_id, full)
    return {"branch": branch, "sha": full, "moved": moved, "pruned_reviews": pruned}


def accepted_note(db, conv_id: str) -> str:
    """Rides the ☏ checkout line: the recorded hand-off, so nobody plans from a stale belief."""
    conv = db.get_conversation(conv_id) or {}
    sha = conv.get("accepted_sha") or ""
    return f" — accepted hand-off: {sha[:12]}" if sha else ""


def handoff_rider(db, conv_id: str) -> str:
    """One line for a captain's wake: the recorded hand-off(s) and where work lives.

    Present facts only, and only hand-offs: the line's part appears once a SHA
    is accepted (with its worktree path), a descendant once it has an accepted
    SHA. A tree with no accepted hand-offs sees nothing, so the rider never
    scrolls and never dresses a mere worktree up as a hand-off.
    """
    parts = []
    conv = db.get_conversation(conv_id) or {}
    if conv.get("accepted_sha"):
        own = [f"accepted {conv['accepted_sha'][:12]}"]
        if conv.get("cwd"):
            own.append(f"worktree {conv['cwd']}")
        parts.append(" ".join(own))
    try:
        children = descendants(db, conv_id)
    except AttributeError:
        children = []  # a minimal db without the tree query: own facts only
    for child_id in children:
        child = db.get_conversation(child_id) or {}
        if not child.get("accepted_sha"):
            continue
        where = f" · worktree {child['cwd']}" if child.get("cwd") else ""
        parts.append(f"«{child.get('name') or child_id}» "
                     f"accepted {child['accepted_sha'][:12]}{where}")
    if not parts:
        return ""
    return "(hand-off: " + "; ".join(parts) + ")"


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
