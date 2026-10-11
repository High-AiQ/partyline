"""Per-line worktree and review/scratch-checkout carve-outs for the write fence."""

from __future__ import annotations

import os
import re

from . import git_fence
from .line_worktree import REVIEW_DIR, repo_root
from .scratch_worktrees import SCRATCH_DIR


def _checkout_directory(cwd: str, directory: str, *, create: bool = False) -> str | None:
    """Return the repository's canonical checkout directory, creating it for a bind."""
    repo = repo_root(cwd)
    if repo is None:
        return None
    root = os.path.join(os.path.realpath(repo), directory)
    if create and not os.path.lexists(root):
        try:
            os.mkdir(root)
        except FileExistsError:
            pass
        except OSError:
            return None
    if not os.path.isdir(root) or os.path.islink(root) or os.path.realpath(root) != root:
        return None
    return root


def _review_directory(cwd: str, *, create: bool = False) -> str | None:
    return _checkout_directory(cwd, REVIEW_DIR, create=create)


def _scratch_directory(cwd: str, *, create: bool = False) -> str | None:
    return _checkout_directory(cwd, SCRATCH_DIR, create=create)


def _recorded_checkouts(att: dict, key: str, repo: str, directory: str) -> list[str]:
    """Return recorded, canonical checkouts of one kind for binds only.

    A recorded path counts only when it is exactly ``<repo>/<directory>/<sha>``
    for the attachment's own line, a real directory, and a worktree git knows
    inside that repository — anything else is somebody else's tree or a trap.
    """
    conv_id = att.get("conv_id")
    rows = att.get(key) or []
    paths = []
    for row in rows:
        if not isinstance(row, dict) or row.get("conv_id") != conv_id:
            continue
        sha, recorded = row.get("sha"), row.get("path")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
            continue
        expected = os.path.join(repo, directory, sha)
        if (not isinstance(recorded, str) or not os.path.isabs(recorded) or
                recorded != expected or os.path.islink(recorded) or
                os.path.realpath(recorded) != recorded or not os.path.isdir(recorded)):
            continue
        if (git_fence._worktree_gitdir(recorded) is None or
                os.path.realpath(repo_root(recorded) or "") != repo):
            continue
        paths.append(recorded)
    return paths


def _review_worktree_paths(att: dict, review_root: str | None = None) -> list[str]:
    """Return recorded, canonical review checkouts for metadata binds only."""
    conv_id = att.get("conv_id")
    cwd = att.get("cwd") or ""
    if not (att.get("review_worktrees") or []) or not conv_id:
        return []
    repo = repo_root(cwd)
    if repo is None:
        return []
    repo = os.path.realpath(repo)
    if (review_root or _review_directory(cwd)) != os.path.join(repo, REVIEW_DIR):
        return []
    return _recorded_checkouts(att, "review_worktrees", repo, REVIEW_DIR)


def _scratch_worktree_paths(att: dict, scratch_root: str | None = None) -> list[str]:
    """Return recorded, canonical scratch checkouts: the line's build homes."""
    conv_id = att.get("conv_id")
    cwd = att.get("cwd") or ""
    if not (att.get("scratch_worktrees") or []) or not conv_id:
        return []
    repo = repo_root(cwd)
    if repo is None:
        return []
    repo = os.path.realpath(repo)
    if (scratch_root or _scratch_directory(cwd)) != os.path.join(repo, SCRATCH_DIR):
        return []
    return _recorded_checkouts(att, "scratch_worktrees", repo, SCRATCH_DIR)


def _checkout_git_binds(path: str, cwd: str, conv_id: str) -> list[tuple[str, str, bool]]:
    """Avoid shadowing refs when a checkout shares the root checkout's own Git dir."""
    gitdir = git_fence._worktree_gitdir(path)
    if gitdir is not None:
        common = os.path.realpath(git_fence.common_gitdir(gitdir))
        primary = git_fence._worktree_gitdir(cwd)
        if primary and os.path.realpath(git_fence.common_gitdir(primary)) == common:
            # The primary worktree already prepared this line's shared mirror.
            # Refreshing it for a detached review would overwrite the line tip.
            return [(gitdir, gitdir, False)]
        cwd_real = os.path.realpath(cwd or "")
        if common == cwd_real or common.startswith(cwd_real + os.sep):
            return []
    return git_fence.git_binds(path, conv_id)


# Kept for the fence tests that name it directly.
_review_git_binds = _checkout_git_binds


def write_set(att: dict) -> list[tuple[str, str, bool]]:
    """Ordered writable Git, cwd, review, and scratch carve-outs for bubblewrap."""
    covered: set[str] = set()
    binds: list[tuple[str, str, bool]] = []

    def add(path: str) -> None:
        path = os.path.normpath(path)
        if path in covered or not os.path.lexists(path):
            return
        covered.add(path)
        binds.append((path, path, False))

    cwd = att.get("cwd") or ""
    conv_id = att.get("conv_id") or ""
    add(cwd)
    for src, dst, read_only in git_fence.git_binds(cwd, conv_id):
        if src not in covered:
            covered.add(src)
            binds.append((src, dst, read_only))
    review_root = _review_directory(cwd, create=True)
    if review_root:
        add(review_root)
    for path in _review_worktree_paths(att, review_root):
        for src, dst, read_only in _checkout_git_binds(path, cwd, conv_id):
            if src not in covered:
                covered.add(src)
                binds.append((src, dst, read_only))
    scratch_root = _scratch_directory(cwd, create=True)
    if scratch_root:
        add(scratch_root)
    for path in _scratch_worktree_paths(att, scratch_root):
        for src, dst, read_only in _checkout_git_binds(path, cwd, conv_id):
            if src not in covered:
                covered.add(src)
                binds.append((src, dst, read_only))
    return binds


def darwin_write_set(att: dict) -> list[str]:
    """Writable cwd and Git carve-outs; Darwin's weaker Git scope is documented."""
    paths: list[str] = []
    covered: set[str] = set()

    def add(path: str) -> None:
        if not path:
            return
        path = os.path.normpath(path)
        if path not in covered and os.path.lexists(path):
            covered.add(path)
            paths.append(path)

    cwd = att.get("cwd") or ""
    add(cwd)
    for path in git_fence.darwin_write_paths(cwd):
        add(path)
    review_root = _review_directory(cwd, create=True)
    if review_root:
        add(review_root)
    for path in _review_worktree_paths(att, review_root):
        add(path)
        add(git_fence._worktree_gitdir(path) or "")
    scratch_root = _scratch_directory(cwd, create=True)
    if scratch_root:
        add(scratch_root)
    for path in _scratch_worktree_paths(att, scratch_root):
        add(path)
        add(git_fence._worktree_gitdir(path) or "")
    return paths
