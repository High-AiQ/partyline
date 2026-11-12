"""Ending a line's worktree: the SAFE removal test, archive, and the startup sweep.

A worktree a line was placed in is not removed unconditionally the way purge
removes it — archive and a captain's own retirement both need to know
whether removing it would lose real work first. SAFE means the working tree
is clean and every reachable commit is in the parent or default branch.
Anything Git cannot verify stays unsafe.
"""

from __future__ import annotations

import logging
import os
import subprocess

from .worktree_cleanup import cleanup, reclaim_task, task_disposable
from .worktree_storage import reclaim_ignored, record_kept
from .git_fence import mirror_branch_ref
from .hierarchy import parent_id_of
from .line_worktree import WORKTREES_DIR, _git, line_cwd, repo_root
from .worktree_paths import branch_name, managed_root
from .retirement_worktree import remove_directory
from .retirement_orphan import empty_merged, empty_task, remove_empty, remove_task
from .storage_ignored import ignored_reason
from .nested_repositories import keep_reason, nested_repositories
from .review_worktrees import sweep_review_worktrees
from .task_teardown import teardown
from .task_workspaces import tip, workspaces
from .scratch_worktrees import sweep_scratch_worktrees

logger = logging.getLogger(__name__)


def _worktree_root(cwd: str) -> str | None:
    """The repository a worktree at ``cwd`` belongs to, or None when ``cwd``
    is not one of ours."""
    if not os.path.isdir(cwd):
        return None
    return managed_root(cwd)


def remove_for_line(conv: dict | None, db=None) -> None:
    """Drop the worktree a purged line was placed in; its branch stays."""
    cwd = (conv or {}).get("cwd") or ""
    root = _worktree_root(cwd)
    if root is not None and remove_empty(root, cwd, conv_id=(conv or {}).get("id")):
        return
    if db and remove_task(db, conv):
        return
    if root is not None and keep_reason(cwd, lenient=True):
        return
    if db is not None and root is not None:
        teardown(db, conv["id"], cwd)  # a task's commits and nested worktrees first
    if root is None or not os.path.lexists(os.path.join(cwd, ".git")) or keep_reason(cwd):
        return
    try:
        if ignored_reason(cwd):
            return
        remove_directory(cwd, root)
        _git("worktree", "remove", "--force", cwd, cwd=root)
    except (OSError, subprocess.SubprocessError):
        pass


def _current_branch(cwd: str) -> str | None:
    try:
        done = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None


def _base_ref(cwd: str | None) -> str | None:
    """A merge base for the SAFE test: the checkout's branch, or its commit.

    Never the literal ``HEAD``: as a ``rev-list --not`` base inside a child
    worktree it would resolve to that child's own tip and prove every commit
    merged, so a detached checkout contributes its resolved commit instead.
    """
    if not cwd:
        return None
    branch = _current_branch(cwd)
    if branch and branch != "HEAD":
        return branch
    try:
        done = _git("rev-parse", "HEAD", cwd=cwd)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() or None


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
    return _base_ref(root)


def _is_clean(cwd: str) -> bool:
    """Clean to git, and holding no repository of its own that git cannot see."""
    if nested_repositories(cwd, lenient=True):
        return False
    if not os.path.lexists(os.path.join(cwd, ".git")):
        return True  # a task folder of worktrees only: each was checked as nested
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


def _workspace_merged(db, conv_id: str, item: dict) -> bool:
    """Every commit on a task's branch in one clone is in that clone's own checkout or default."""
    repo = item["repository"]
    if empty_merged(repo, item["path"], item["branch"], conv_id):
        return True
    bases = [b for b in (_base_ref(repo), _default_branch(repo)) if b]
    tips = [t for t in (tip(item, conv_id), _base_ref(item["path"])) if t]
    return bool(bases) and bool(tips) and all(_in_history(item["path"], t, bases) for t in tips)


def worktree_state(db, conv: dict | None) -> dict | None:
    """Return clean/merged/nested evidence, or None for an inherited directory.

    Every reachable tip must be in the parent or default branch. Git failures
    are unsafe. Empty pruned checkouts use their surviving assigned branches.
    """
    conv = conv or {}
    cwd = conv.get("cwd") or ""
    root = _worktree_root(cwd)
    if root is None:
        return None
    if empty_merged(root, cwd, conv_id=conv.get("id")) or empty_task(db, conv):
        return {"clean": True, "merged": True, "nested": []}
    if (spaces := workspaces(db, conv.get("id") or "")):
        return {"clean": _is_clean(cwd), "nested": nested_repositories(cwd, lenient=True),
                "merged": all(_workspace_merged(db, conv["id"], item) for item in spaces)}
    branch = _current_branch(cwd)
    parent_cwd = line_cwd(db, parent_id_of(conv)) if parent_id_of(conv) else None
    bases = [b for b in (_base_ref(parent_cwd), _default_branch(root)) if b]
    mirror = mirror_branch_ref(cwd, conv.get("id") or "", branch_name(cwd))
    tips = [tip for tip in dict.fromkeys((branch, "HEAD", mirror)) if tip]
    merged = bool(bases) and bool(tips) and all(_in_history(cwd, t, bases) for t in tips)
    return {"clean": _is_clean(cwd), "merged": merged, "nested": nested_repositories(cwd)}


def worktree_removal_reason(db, conv: dict | None) -> str | None:
    """Why a line's worktree cannot be removed right now, or None when SAFE.

    A line with no worktree of its own (a shared or inherited directory) has
    nothing to keep, so it reads as SAFE too.
    """
    state = worktree_state(db, conv)
    if state is None:
        return None
    conv_cwd = (conv or {}).get("cwd") or ""
    if (reason := keep_reason(conv_cwd, lenient=True)):
        return reason
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
    from .storage_worktrees import in_use
    if in_use(db, conv.get("cwd") or "", conv):
        return False
    state = worktree_state(db, conv)
    if state is None or not state["merged"]:
        return False
    if (spaces := workspaces(db, conv_id)):
        if not task_disposable(spaces, conv["cwd"]):
            reclaim_task(spaces, conv["cwd"])
            return False
        remove_for_line(conv, db)
        reclaim_task(spaces, conv.get("cwd") or "")
        return not os.path.isdir(conv.get("cwd") or "")
    return cleanup(db, _worktree_root(conv["cwd"]), conv["cwd"], True, force=True)[0]


def archive_worktree_if_safe(db, conv_id: str, *, preserve: bool = True) -> tuple[bool, str | None]:
    """Remove merged worktrees, preserving dirty state outside them first.

    With preserve=False, remove only clean disposable trees. Return the removal
    result and any reason kept; inherited directories report (False, None).
    """
    conv = db.get_conversation(conv_id)
    cwd = (conv or {}).get("cwd") or ""
    if _worktree_root(cwd) is None:
        return False, None
    from .storage_worktrees import in_use
    if protection := in_use(db, cwd, conv):
        return False, protection
    if empty_merged(_worktree_root(cwd), cwd, conv_id=conv_id) or empty_task(db, conv):
        remove_for_line(conv, db)
        return not os.path.isdir(cwd), None
    if not preserve:
        reason = worktree_removal_reason(db, conv)
        if reason:
            return False, reason
        if not task_disposable(workspaces(db, conv_id), cwd):
            return False, "contains repositories or uninspectable files"
        remove_for_line(conv, db)
        return not os.path.isdir(cwd), None
    state = worktree_state(db, conv)
    spaces = workspaces(db, conv_id)
    disposable = bool(spaces) and task_disposable(spaces, cwd)
    if disposable and state["clean"] and state["merged"]:
        remove_for_line(conv, db)
        return not os.path.isdir(cwd), None
    if spaces:
        reclaim_task(spaces, cwd)
        if disposable and not state["merged"]:
            try:
                record_kept(db, _worktree_root(cwd), cwd, "unmerged commits")
            except OSError:
                pass
            return False, "unmerged commits"
    return cleanup(db, _worktree_root(cwd), cwd, state["merged"])


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
        _sweep_repo(root, known_cwds, db)
        sweep_review_worktrees(db, root)
        sweep_scratch_worktrees(db, root)


def _sweep_repo(root: str, known_cwds: set[str], db=None) -> None:
    worktrees_dir = os.path.join(root, WORKTREES_DIR)
    if os.path.isdir(worktrees_dir):
        for name in sorted(os.listdir(worktrees_dir)):
            path = os.path.join(worktrees_dir, name)
            if os.path.islink(path) or not os.path.isdir(path) or path in known_cwds:
                continue
            bases = [base for base in (_default_branch(root),) if base]
            merged = bool(bases) and _in_history(path, "HEAD", bases)
            if db is not None:
                removed, reason = cleanup(db, root, path, merged)
                logger.info("worktree sweep: %s %s (%s)",
                            "removed" if removed else "kept", path, reason or "safe")
            else:
                reclaim_ignored(path)
    try:
        _git("worktree", "prune", cwd=root)
    except (OSError, subprocess.SubprocessError):
        pass
