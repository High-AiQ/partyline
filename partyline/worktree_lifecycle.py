"""Ending a line's worktree: the SAFE removal test, archive, and the startup sweep.

A worktree a line was placed in is not removed unconditionally the way purge
removes it — archive and a captain's own retirement both need to know
whether removing it would lose real work first. SAFE means the working tree
is clean and every commit reachable from the worktree's HEAD — its branch,
or a detached tip that lives on no branch — is reachable from the parent
line's branch or the repository's default branch: nothing sits only in the
worktree about to disappear. Anything git cannot verify reads as
unsafe, never as SAFE by default — a repository that a git command cannot
inspect is not evidence that nothing would be lost.
"""

from __future__ import annotations

import logging
import os
import subprocess

from .hierarchy import parent_id_of
from .line_worktree import WORKTREES_DIR, _git, line_cwd, repo_root
from .review_worktrees import sweep_review_worktrees

logger = logging.getLogger(__name__)


def _worktree_root(cwd: str) -> str | None:
    """The repository a worktree at ``cwd`` belongs to, or None when ``cwd``
    is not one of ours."""
    if f"/{WORKTREES_DIR}/" not in cwd or not os.path.isdir(cwd):
        return None
    return cwd.split(f"/{WORKTREES_DIR}/")[0]


def remove_for_line(conv: dict | None) -> None:
    """Drop the worktree a purged line was placed in; its branch stays."""
    cwd = (conv or {}).get("cwd") or ""
    root = _worktree_root(cwd)
    if root is None:
        return
    try:
        _git("worktree", "remove", "--force", cwd, cwd=root)
    except (OSError, subprocess.SubprocessError):
        pass


def _current_branch(cwd: str) -> str | None:
    try:
        done = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None


def _default_branch(root: str) -> str | None:
    """The repository's real default branch, not whatever the main checkout
    happens to have live right now — a root left on a feature branch must
    not make an already-merged child read as unmerged."""
    try:
        done = _git("symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD", cwd=root)
    except (OSError, subprocess.SubprocessError):
        done = None
    if done is not None and done.returncode == 0 and done.stdout.strip():
        return done.stdout.strip()
    return _current_branch(root)


def _is_clean(cwd: str) -> bool:
    try:
        done = _git("status", "--porcelain", cwd=cwd)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0 and not done.stdout.strip()


def _in_history(cwd: str, tip: str, bases: list[str]) -> bool:
    """True when every commit reachable from ``tip`` is reachable from ``bases``.

    Run in the worktree, not the main repository: ``HEAD`` there means the
    worktree's own checkout, so a detached tip's commits are counted instead
    of resolving to whatever the main checkout happens to have live.
    """
    try:
        done = _git("rev-list", tip, "--not", *bases, cwd=cwd)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0 and not done.stdout.strip()


def worktree_state(db, conv: dict | None) -> dict | None:
    """The line's own worktree as ``{"clean": bool, "merged": bool}``.

    ``None`` when the line has no worktree of its own (a shared or inherited
    directory has nothing to keep). ``merged`` is False whenever git cannot
    prove every commit reachable from the worktree's HEAD — its branch, or a
    detached tip that lives on no branch — is reachable from the parent
    line's branch or the repository default. An unverifiable state never
    reads as merged, exactly as the SAFE test never reads an uninspectable
    repository as safe.
    """
    conv = conv or {}
    cwd = conv.get("cwd") or ""
    root = _worktree_root(cwd)
    if root is None:
        return None
    branch = _current_branch(cwd)
    parent_cwd = line_cwd(db, parent_id_of(conv)) if parent_id_of(conv) else None
    bases = [b for b in (_current_branch(parent_cwd) if parent_cwd else None,
                         _default_branch(root)) if b]
    tips = [tip for tip in dict.fromkeys((branch, "HEAD")) if tip]
    merged = bool(bases) and bool(tips) and all(_in_history(cwd, t, bases) for t in tips)
    return {"clean": _is_clean(cwd), "merged": merged}


def worktree_removal_reason(db, conv: dict | None) -> str | None:
    """Why a line's worktree cannot be removed right now, or None when SAFE.

    A line with no worktree of its own (a shared or inherited directory) has
    nothing to keep, so it reads as SAFE too.
    """
    state = worktree_state(db, conv)
    if state is None:
        return None
    if not state["clean"]:
        return "uncommitted changes"
    if not state["merged"]:
        return "unmerged commits"
    return None


def discard_worktree(db, conv_id: str) -> bool:
    """Force-remove a merged line's worktree, discarding uncommitted changes.

    The explicit ``discard`` path a person or captain passes when the branch
    is already merged. It refuses an unmerged branch outright: those commits
    exist only in the worktree, and a discard must never destroy them.
    """
    conv = db.get_conversation(conv_id) or {}
    state = worktree_state(db, conv)
    if state is None or not state["merged"]:
        return False
    remove_for_line(conv)
    return not os.path.isdir(conv.get("cwd") or "")


def archive_worktree_if_safe(db, conv_id: str) -> tuple[bool, str | None]:
    """Remove a line's worktree when SAFE; otherwise leave it and say why.

    Returns ``(removed, kept_reason)``. A line with no worktree of its own
    reports ``(False, None)`` too — SAFE and "removed" are not the same
    thing, and a caller that only checked the reason would tell a person a
    root line's worktree was removed when nothing was ever there to touch.
    """
    conv = db.get_conversation(conv_id)
    cwd = (conv or {}).get("cwd") or ""
    if _worktree_root(cwd) is None:
        return False, None
    reason = worktree_removal_reason(db, conv)
    if reason is not None:
        return False, reason
    remove_for_line(conv)
    return True, None


def sweep_orphaned_worktrees(db) -> None:
    """At startup, drop worktrees under every known repository whose line no
    longer exists in the database.

    Archive and purge remove a worktree as part of the same request, but a
    server stopped mid-request, or a database edited by hand, can leave one
    behind. This never touches a worktree that still belongs to a line —
    live or archived.
    """
    conversations = db.list_conversations(archived=False) + db.list_conversations(archived=True)
    known_cwds = {row["cwd"] for row in conversations if row.get("cwd")}
    # A line's cwd column is written once it is placed, but a root line's own
    # cwd lives only on its attachments — its conversation row is never
    # written. Without this, a repo whose every child line was purged (the
    # accumulation this sweep exists for) contributes no root at all.
    attachment_cwds = db._exec(
        "SELECT DISTINCT cwd FROM attachments WHERE cwd IS NOT NULL AND cwd != ''"
    ).fetchall()
    known_cwds |= {row["cwd"] for row in attachment_cwds}
    # Ask git for the repo, not string-splitting on WORKTREES_DIR: every known
    # cwd — a repo's own root as much as a worktree under it — names a root.
    roots = {root for cwd in known_cwds if (root := repo_root(cwd))}
    for root in sorted(roots):
        _sweep_repo(root, known_cwds)
        sweep_review_worktrees(db, root)


def _sweep_repo(root: str, known_cwds: set[str]) -> None:
    worktrees_dir = os.path.join(root, WORKTREES_DIR)
    if os.path.isdir(worktrees_dir):
        for name in sorted(os.listdir(worktrees_dir)):
            path = os.path.join(worktrees_dir, name)
            if not os.path.isdir(path) or path in known_cwds:
                continue
            if _is_clean(path):
                _git("worktree", "remove", "--force", path, cwd=root)
                logger.info("worktree sweep: removed orphaned worktree %s", path)
            else:
                logger.info("worktree sweep: kept dirty orphaned worktree %s", path)
    try:
        _git("worktree", "prune", cwd=root)
    except (OSError, subprocess.SubprocessError):
        pass
