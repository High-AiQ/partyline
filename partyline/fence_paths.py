"""Per-line worktree and review-checkout carve-outs for the write fence."""

from __future__ import annotations

import os
import re

from . import git_fence
from .line_worktree import REVIEW_DIR, repo_root


def _review_directory(cwd: str, *, create: bool = False) -> str | None:
    """Return the repository's canonical .review directory, creating it for a bind."""
    repo = repo_root(cwd)
    if repo is None:
        return None
    review_root = os.path.join(os.path.realpath(repo), REVIEW_DIR)
    if create and not os.path.lexists(review_root):
        try:
            os.mkdir(review_root)
        except FileExistsError:
            pass
        except OSError:
            return None
    if (not os.path.isdir(review_root) or os.path.islink(review_root) or
            os.path.realpath(review_root) != review_root):
        return None
    return review_root


def _review_worktree_paths(att: dict, review_root: str | None = None) -> list[str]:
    """Return recorded, canonical review checkouts for metadata binds only."""
    conv_id = att.get("conv_id")
    cwd = att.get("cwd") or ""
    rows = att.get("review_worktrees") or []
    repo = repo_root(cwd) if rows and conv_id else None
    if repo is None:
        return []
    repo = os.path.realpath(repo)
    expected_root = os.path.join(repo, REVIEW_DIR)
    review_root = review_root or _review_directory(cwd)
    if review_root != expected_root:
        return []

    paths = []
    for row in rows:
        if not isinstance(row, dict) or row.get("conv_id") != conv_id:
            continue
        sha, recorded = row.get("sha"), row.get("path")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
            continue
        expected = os.path.join(review_root, sha)
        if (not isinstance(recorded, str) or not os.path.isabs(recorded) or
                recorded != expected or os.path.islink(recorded) or
                os.path.realpath(recorded) != recorded or not os.path.isdir(recorded)):
            continue
        if (git_fence._worktree_gitdir(recorded) is None or
                os.path.realpath(repo_root(recorded) or "") != repo):
            continue
        paths.append(recorded)
    return paths


def _review_git_binds(path: str, cwd: str, conv_id: str) -> list[tuple[str, str, bool]]:
    """Avoid shadowing refs when a review worktree shares the root checkout's own Git dir."""
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


def write_set(att: dict) -> list[tuple[str, str, bool]]:
    """Ordered writable Git, cwd, and review carve-outs for bubblewrap."""
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
        for src, dst, read_only in _review_git_binds(path, cwd, conv_id):
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
    return paths
