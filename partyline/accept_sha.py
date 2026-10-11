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

import logging
import os
import re

from fastapi import HTTPException, Request

from .auth_guard import request_principal
from .accept_history import record_accept
from .git_fence import mirror_branch_ref
from .hierarchy import ancestors, descendants, parent_id_of
from .hierarchy_contracts import AcceptIn, AcceptResponse, TipResponse, TreeSyncOut
from .line_worktree import _git, line_cwd, repo_and_worktree, rev
from .worktree_paths import branch_name, managed_root
from .machine_scope import deny_unless
from .prereview import tree_sync_check
from .review_worktrees import prune_accepted_review
from .system_notice import post_system_notice
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
    return branch_name(cwd)


def _git_failure(done, fallback: str) -> AcceptError:
    lines = [line for line in (done.stderr or "").splitlines() if line.strip()]
    return AcceptError(409, f"{fallback}: {lines[-1]}" if lines else fallback)


def _descends(root: str, older: str, newer: str) -> bool:
    """``git merge-base --is-ancestor`` as a predicate."""
    return _git("merge-base", "--is-ancestor", older, newer, cwd=root).returncode == 0


def _move_branch(
    root: str, worktree: str | None, branch: str, full: str, head: str,
    fenced: bool = False,
) -> None:
    """Fast-forward the line's real branch to the accepted SHA.

    Non-fenced, the worktree holding the branch merges ``--ff-only``, which
    refuses a dirty tree and carries the files along. On the fenced path the
    real ref moves by compare-and-swap — ``update-ref`` names the previously
    read tip as the value it expects to replace, so a concurrent move is
    refused, never clobbered; the fenced worktree already holds the accepted
    content, so nothing is checked out over it.
    """
    if not fenced and worktree and os.path.isdir(worktree):
        if rev(worktree, "rev-parse", "--abbrev-ref", "HEAD") == branch:
            done = _git("merge", "--ff-only", "--quiet", full, cwd=worktree)
            if done.returncode != 0:
                raise _git_failure(done, f"cannot fast-forward {branch} in the worktree")
            return
    done = _git("update-ref", f"refs/heads/{branch}", full, head, cwd=root)
    if done.returncode != 0:
        raise _git_failure(done, f"cannot move {branch} to the accepted SHA")


def accept_sha(db, conv_id: str, sha: str, allow_descendant: bool = False) -> dict:
    """Verify the SHA, fast-forward the line's branch to it, and record it.

    Returns ``{"branch": name, "sha": full, "moved": bool, "reviewed_sha": ...}``
    — ``moved`` is False when the branch already pointed at the SHA, so
    re-accepting is a clean no-op that leaves the record in place. Under the
    write fence the line commits to its mirror branch, so when a mirror
    exists its tip must be the SHA or an ancestor of it — a mirror holding
    work the SHA does not include is refused as a stray. A reviewed SHA the
    mirror tip descends *from* — the worker committed again after the review
    — is refused too, unless ``allow_descendant`` lands the branch on the
    newer tip instead, naming both SHAs in the response.
    """
    conv = db.get_conversation(conv_id)
    if conv is None:
        raise AcceptError(404, "line not found")
    cwd = line_cwd(db, conv_id) or ""
    root, worktree = repo_and_worktree(cwd)
    if root is None or not managed_root(cwd):
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
    mirror_head = mirror_branch_ref(cwd, conv_id, branch)
    reviewed = full
    past_review = None
    if (allow_descendant and mirror_head is not None and mirror_head != full
            and _descends(root, full, mirror_head)):
        # The line kept committing after the reviewed hand-off: the fenced
        # tip descends from the reviewed SHA. Accept by fast-forwarding to
        # the tip instead of refusing the reviewed SHA as a stray; the
        # response names both, and the notice counts what went in unreviewed.
        past_review = int(rev(root, "rev-list", "--count", f"{reviewed}..{mirror_head}") or 0)
        full = mirror_head
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
        # Descent from the branch point. A branch sitting exactly at its
        # merge-base with the parent has no real commits of its own, so a
        # foreign SHA used to be refused outright. Under the write fence that
        # is exactly where every fenced hand-off lands: the line's commits
        # live on its mirror branch and the real ref never moved. The mirror
        # decides — its tip must be the SHA or an ancestor of it, so the
        # accepted SHA carries every commit the line actually made; a mirror
        # ahead of or diverging from the SHA is a stray commit. With no
        # mirror the old refusal stands: land the work on the branch first.
        if mirror_head is not None:
            if mirror_head != full and not _descends(root, mirror_head, full):
                raise AcceptError(
                    409,
                    f"{name} is not this line's fenced tip {mirror_head[:12]} — "
                    "a stray commit; hand off the SHA the line's branch actually holds",
                )
        else:
            parent_tip = _base_ref(
                line_cwd(db, parent_id_of(conv)) if parent_id_of(conv) else None)
            lineage = rev(root, "merge-base", branch, parent_tip) if parent_tip else None
            landed = bool(parent_tip) and rev(root, "merge-base", parent_tip, full) == full
            if lineage == head and not landed:
                raise AcceptError(
                    409,
                    f"{branch} has no commits of its own — it sits at its branch point with the "
                    f"parent, and {name} has not landed there; land the work on the branch first",
                )
        _move_branch(root, worktree, branch, full, head,
                     fenced=mirror_head is not None)
    sync = tree_sync_check(root, branch, full)
    db._exec("UPDATE conversations SET accepted_sha=? WHERE id=?", (full, conv_id))
    pruned = prune_accepted_review(db, conv_id, full)
    if reviewed != full:
        # The tip carries work past the review, so the reviewed SHA's own
        # review worktrees are settled too: prune them with the tip's.
        pruned += prune_accepted_review(db, conv_id, reviewed)
    return {
        "branch": branch, "sha": full, "moved": moved, "pruned_reviews": pruned,
        "reviewed_sha": reviewed if reviewed != full else None,
        "past_review": past_review, "tree_sync": sync,
    }


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
        if child.get("archived_at") or any(
            (db.get_conversation(ancestor) or {}).get("archived_at")
            for ancestor in ancestors(db, child_id)
        ):
            continue
        if not child.get("accepted_sha"):
            continue
        where = f" · worktree {child['cwd']}" if child.get("cwd") else ""
        parts.append(f"«{child.get('name') or child_id}» "
                     f"accepted {child['accepted_sha'][:12]}{where}")
    if not parts:
        return ""
    return "(hand-off: " + "; ".join(parts) + ")"


def _tip_response(db, conv_id: str) -> TipResponse:
    """Where the line's branch and its fence mirror point, read-only.

    A captain needs the fenced tip to plan a hand-off without learning it
    from an accept refusal; the mirror lookup is the one accept uses.
    """
    cwd = line_cwd(db, conv_id) or ""
    root, _worktree = repo_and_worktree(cwd) if cwd else (None, None)
    branch = _branch_name(cwd) if root and managed_root(cwd) else None
    return TipResponse(
        branch=branch,
        branch_sha=rev(root, "rev-parse", "--verify", "--quiet", branch)
        if branch else None,
        fenced_tip=mirror_branch_ref(cwd, conv_id, branch) if branch else None,
    )


def register_accept_route(app, runtime) -> None:
    @app.get("/api/conversations/{conv_id}/tip", response_model=TipResponse)
    async def line_tip(request: Request, conv_id: str):
        db = runtime.db
        deny_unless(db, request_principal(request), conv_id, "read")
        return _tip_response(db, conv_id)

    @app.post("/api/conversations/{conv_id}/accept", response_model=AcceptResponse)
    async def accept(request: Request, conv_id: str, body: AcceptIn):
        db = runtime.db
        principal = request_principal(request)
        deny_unless(db, principal, conv_id, "accept")
        try:
            done = accept_sha(db, conv_id, body.sha, body.allow_descendant)
        except AcceptError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc
        _refresh_children_views(db, conv_id, done["branch"])
        record_accept(db, conv_id, done["sha"], principal.name, body.findings)
        state = "already at" if not done["moved"] else "moved to"
        tail = " — the hand-off is the SHA on the line's branch"
        if done["reviewed_sha"]:
            tail = (f" — reviewed {done['reviewed_sha'][:12]}, fast-forwarded to the line's "
                    f"newer tip ({done['past_review']} commit(s) past the review)")
        if body.findings:
            tail += f" ({len(body.findings)} findings)"
        sync = done["tree_sync"]
        if not sync["ok"]:
            tail += f" ⚠ tree not in sync: {sync['detail']}"
        await post_system_notice(
            runtime,
            conv_id,
            f"☏ hand-off accepted by @{principal.name}: {done['branch']} {state} "
            f"{done['sha'][:12]}{tail}",
            actor=principal,
        )
        return AcceptResponse(
            conv_id=conv_id, branch=done["branch"], sha=done["sha"], moved=done["moved"],
            reviewed_sha=done["reviewed_sha"], tree_sync=TreeSyncOut(**sync),
        )


def _refresh_children_views(db, conv_id: str, branch: str) -> None:
    """Refresh children's launch-time-stale views; best-effort, never fail an accept."""
    try:
        from .line_base import refresh_children_views

        refresh_children_views(db, conv_id, branch)
    except Exception:
        logging.getLogger(__name__).exception(
            "could not refresh children's base views after accepting on %s", conv_id)
