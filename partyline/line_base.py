"""The parent branch as the host sees it, and the line's fenced view of it.

Inside the fence a worktree's view of the host repository's refs is the
line's own copy-on-write mirror, refreshed only at launch: `git fetch
<host> main` answers with main as it was when the line was born, while the
objects are shared, so a merge by SHA from that stale view lands yesterday's
main (finding 2.11). `GET …/base` reports the parent branch as the host sees
it and how far behind the line is; `POST …/refresh-base` re-copies exactly
that one ref into the mirror — never the line's own branch, never any other
ref — so `git merge <branch>` inside the line resolves to today's main. On
Darwin and Windows there is no ref mirror and the real refs are read
directly, so a refresh has nothing to do and reports it.
"""

from __future__ import annotations

import logging
import os

from fastapi import HTTPException, Request

from .auth_guard import request_principal
from .git_fence import (
    _mirror_dir,
    _read_ref,
    _worktree_gitdir,
    common_gitdir,
    mirror_branch_ref,
    _write_mirror_text,
)
from .hierarchy import child_ids, parent_id_of
from .line_worktree import branch_name, line_cwd, repo_and_worktree, rev
from .machine_scope import deny_unless
from .worktree_paths import managed_root

logger = logging.getLogger(__name__)


def _host_default_branch(root: str) -> str | None:
    """The checkout's own current branch — main, for a root-level line's parent."""
    return rev(root, "symbolic-ref", "--quiet", "--short", "HEAD")


def _line_head(db, conv_id: str, line_root: str) -> tuple[str, str] | None:
    """The line's working tip: the fenced mirror's value when one exists.

    Returns ``(branch, sha)``, or None when the line has no resolvable tip.
    """
    cwd = line_cwd(db, conv_id) or ""
    branch = branch_name(cwd)
    if managed_root(cwd):
        tip = mirror_branch_ref(cwd, conv_id, branch) or rev(
            line_root, "rev-parse", "--verify", "--quiet", branch)
        return (branch, tip) if tip else None
    head = rev(line_root, "rev-parse", "--verify", "--quiet", "HEAD")
    return ("HEAD", head) if head else None


def base_report(db, conv_id: str) -> dict:
    """The parent branch as the host sees it, and the line's distance to it."""
    conv = db.get_conversation(conv_id)
    if conv is None:
        raise HTTPException(404, "line not found")
    parent_id = parent_id_of(conv)
    if not parent_id:
        raise HTTPException(409, "this line has no parent line to base on")
    parent_cwd = line_cwd(db, parent_id) or ""
    root, _worktree = repo_and_worktree(parent_cwd) if parent_cwd else (None, None)
    if root is None:
        raise HTTPException(409, "the parent line does not work inside a git repository")
    if managed_root(parent_cwd):
        parent_branch = branch_name(parent_cwd)
    else:
        parent_branch = _host_default_branch(root)
    parent_sha = rev(root, "rev-parse", "--verify", "--quiet", parent_branch or "")
    if parent_sha is None:
        raise HTTPException(
            409, f"the parent branch {parent_branch} does not resolve in the host repository")
    line_root, _line_worktree = repo_and_worktree(line_cwd(db, conv_id) or "")
    if line_root is None:
        raise HTTPException(409, "this line does not work inside a git repository")
    line_base_sha = None
    behind = None
    head = _line_head(db, conv_id, line_root)
    if head is not None:
        base = rev(line_root, "merge-base", head[1], parent_sha)
        if base is not None:
            line_base_sha = base
            behind = int(rev(line_root, "rev-list", "--count", f"{base}..{parent_sha}") or 0)
    return {"parent_branch": parent_branch, "parent_sha": parent_sha,
            "line_base_sha": line_base_sha, "behind": behind}


def refresh_mirror_ref(cwd: str, conv_id: str, branch: str) -> str | None:
    """Point the line's mirror copy of one sibling branch at the real ref.

    Branch views are launch-time fresh, so a long-lived line merges
    yesterday's parent branch; this re-copies exactly that one ref into the
    mirror. The line's own branch and every other mirror ref are untouched.
    Returns the new value, or None when there is nothing to refresh — not a
    linked worktree, no mirror (an unfenced line already reads the real
    refs), or a branch the host does not have.
    """
    gitdir = _worktree_gitdir(cwd)
    if gitdir is None:
        return None
    common = common_gitdir(gitdir)
    mirror = _mirror_dir(common, conv_id)
    if not os.path.isdir(mirror):
        return None
    value = _read_ref(common, f"refs/heads/{branch}")
    if not value:
        return None
    _write_mirror_text(mirror, f"refs/heads/{branch}", value + "\n")
    return value


def refresh_line_base(db, conv_id: str) -> dict:
    """Refresh the line's fenced view of its parent branch; report the base."""
    report = base_report(db, conv_id)
    cwd = line_cwd(db, conv_id) or ""
    refreshed = refresh_mirror_ref(cwd, conv_id, report["parent_branch"])
    if refreshed is None:
        return {**report, "refreshed": False}
    seen = rev(cwd, "rev-parse", "--verify", "--quiet", report["parent_branch"])
    return {**report, "refreshed": True,
            "seen_sha": seen if seen == refreshed else None}


def refresh_children_views(db, conv_id: str, branch: str) -> int:
    """After an accept moves this line's branch, refresh each child's view.

    The children's fenced views are launch-time fresh; without this a
    grandchild merges the parent branch as it stood when the grandchild
    launched. Best-effort by design: a stale view is a nuisance, not a
    reason to fail an accepted hand-off.
    """
    refreshed = 0
    for child_id in child_ids(db, conv_id):
        cwd = line_cwd(db, child_id)
        if cwd and refresh_mirror_ref(cwd, child_id, branch):
            refreshed += 1
    return refreshed


def register_line_base_route(app, runtime) -> None:
    @app.get("/api/conversations/{conv_id}/base")
    async def get_base(request: Request, conv_id: str):
        db = runtime.db
        deny_unless(db, request_principal(request), conv_id, "read")
        try:
            return base_report(db, conv_id)
        except HTTPException:
            raise
        except Exception:
            logger.exception("base report failed for %s", conv_id)
            raise HTTPException(409, "cannot read the line's base") from None

    @app.post("/api/conversations/{conv_id}/refresh-base")
    async def post_refresh_base(request: Request, conv_id: str):
        db = runtime.db
        deny_unless(db, request_principal(request), conv_id, "write")
        try:
            return refresh_line_base(db, conv_id)
        except HTTPException:
            raise
        except Exception:
            logger.exception("base refresh failed for %s", conv_id)
            raise HTTPException(409, "cannot refresh the line's base") from None
