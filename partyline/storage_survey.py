"""What Partyline stores on disk, and which of it nothing still needs.

Sizes are measured when someone asks, in a thread, under one time budget; a
category that runs out of time reports what it counted and is marked
approximate. Nothing here scans in the background. A *candidate* is a
directory Partyline can recreate or no longer needs; the clear route re-runs
the same checks right before it removes anything.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import attachment_tmp
from .line_worktree import _git, repo_root, rev

SESSIONS_ROOT = os.path.expanduser("~/.partyline/sessions")
SESSION_HOME_KINDS = ("codex", "pi")  # id-keyed homes; fence mirrors and logs are not ours to clear
LIVE = ("starting", "running")
BUDGET_SECONDS = 10.0


class Budget:
    """A shared deadline; ``approximate`` turns true when a walk had to stop."""

    def __init__(self, seconds: float | None = None):
        self.deadline = time.monotonic() + (BUDGET_SECONDS if seconds is None else seconds)
        self.approximate = False

    def slice(self, parts: int) -> Budget:
        share = max(self.deadline - time.monotonic(), 0) / max(parts, 1)
        return Budget(share)

    def size(self, path, skip: frozenset = frozenset()) -> int:
        """Bytes under ``path`` (a file counts itself); symlinks are never followed.

        Directories named in ``skip`` are left out: they were measured separately.
        """
        total, stack = 0, [str(path)]
        while stack:
            if time.monotonic() > self.deadline:
                self.approximate = True
                break
            current = stack.pop()
            try:
                if os.path.islink(current):
                    continue
                if not os.path.isdir(current):
                    total += os.lstat(current).st_size
                    continue
                with os.scandir(current) as entries:
                    for entry in entries:
                        try:
                            if entry.is_symlink():
                                continue
                            if entry.path in skip:
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(entry.path)
                            else:
                                total += entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            continue
            except OSError:
                continue
        return total


@dataclass
class Category:
    key: str
    label: str
    paths: list[str]
    clearable: bool = True
    candidates: list[str] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)


def inside(path: str, base: str) -> bool:
    path, base = os.path.realpath(path), os.path.realpath(base)
    return path == base or path.startswith(base + os.sep)


def live_cwds(db) -> list[str]:
    return [row["cwd"] for row in db._exec(
        "SELECT cwd FROM attachments WHERE status IN ('starting','running') AND cwd IS NOT NULL"
    ).fetchall()]


def planned_ids(db) -> set[str]:
    """Attachments a saved restart plan will reattach: their data is never cleared."""
    row = db._exec("SELECT attachment_ids FROM restart_plan").fetchone()
    try:
        return {str(item) for item in json.loads(row["attachment_ids"])} if row else set()
    except (TypeError, ValueError):
        return set()


def _in_use(db, att_id: str, planned: set[str]) -> str | None:
    att = db.get_attachment(att_id)
    if att_id in planned:
        return "in the saved restart plan"
    if att and att["status"] in LIVE:
        return "its process is running"
    return None


def session_candidates(db) -> Category:
    cat = Category("sessions", "CLI session homes", [SESSIONS_ROOT])
    planned = planned_ids(db)
    for kind in SESSION_HOME_KINDS:
        base = os.path.join(SESSIONS_ROOT, kind)
        try:
            names = sorted(os.listdir(base))
        except OSError:
            continue
        for name in names:
            path = os.path.join(base, name)
            if os.path.islink(path) or not os.path.isdir(path):
                continue
            att = db.get_attachment(name)
            reason = _in_use(db, name, planned)
            if reason is None and att is not None:
                conv = db.get_conversation(att["conv_id"]) or {}
                if att.get("cli_session") and not conv.get("archived_at"):
                    reason = "it can still be resumed"
            if reason:
                cat.skipped.append({"path": path, "reason": reason})
            else:
                cat.candidates.append(path)
    return cat


def tmp_candidates(db) -> Category:
    base = attachment_tmp.base_dir()
    cat = Category("tmp", "Temporary files", [str(base)])
    planned = planned_ids(db)
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return cat
    for name in names:
        if not attachment_tmp.ID_PATTERN.match(name):
            continue
        path = attachment_tmp.guarded_path(name)
        if path is None:
            continue
        reason = _in_use(db, name, planned)
        if reason:
            cat.skipped.append({"path": str(path), "reason": reason})
        else:
            cat.candidates.append(str(path))
    return cat


def known_repositories(db) -> list[str]:
    roots: set[str] = set()
    for archived in (False, True):
        for conv in db.list_conversations(archived=archived):
            cwds = [conv.get("cwd"), *(att.get("cwd") for att in db.list_attachments(conv["id"]))]
            for cwd in cwds:
                root = repo_root(cwd) if cwd else None
                if root:
                    roots.add(os.path.realpath(root))
    return sorted(roots)


def _entries(root: str, directory: str) -> list[str]:
    base = os.path.join(root, directory)
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return []
    return [os.path.join(base, name) for name in names
            if os.path.isdir(os.path.join(base, name)) and not os.path.islink(os.path.join(base, name))]


def _protected_review(db) -> set[str]:
    kept: set[str] = set()
    for row in db._exec("SELECT review_worktree, repositories FROM task_reviews "
                        "WHERE status='in_review'").fetchall():
        kept.add(row["review_worktree"] or "")
        try:
            kept.update(item["path"] for item in json.loads(row["repositories"] or "[]"))
        except (TypeError, ValueError, KeyError):
            pass
    return {os.path.realpath(path) for path in kept if path}


def _preserved(db, path: str) -> bool:
    return db._exec("SELECT 1 FROM retirement_preserved_paths WHERE path=?", (path,)).fetchone() is not None


def review_candidates(db) -> Category:
    cat = Category("review", "Review checkouts", [])
    protected, cwds = _protected_review(db), live_cwds(db)
    for root in known_repositories(db):
        folder = os.path.join(root, ".review")
        if not os.path.isdir(folder):
            continue
        cat.paths.append(folder)
        for path in _entries(root, ".review"):
            reason = ("an in-review task uses it" if os.path.realpath(path) in protected
                      else "a running process works in it" if any(inside(cwd, path) for cwd in cwds)
                      else "a retired line preserved it" if _preserved(db, path) else None)
            if reason:
                cat.skipped.append({"path": path, "reason": reason})
            else:
                cat.candidates.append(path)
    return cat


def default_branch(root: str) -> str | None:
    head = rev(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if head:
        return head
    for name in ("main", "master"):
        if rev(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}"):
            return name
    return None


def scratch_candidates(db) -> Category:
    cat = Category("scratch", "Scratch worktrees", [])
    cwds = live_cwds(db)
    for root in known_repositories(db):
        folder = os.path.join(root, ".scratch")
        if not os.path.isdir(folder):
            continue
        cat.paths.append(folder)
        branch = default_branch(root)
        for path in _entries(root, ".scratch"):
            if any(inside(cwd, path) for cwd in cwds):
                reason = "a running process works in it"
            elif branch is None:
                reason = "the repository has no main branch to compare with"
            elif (head := rev(path, "rev-parse", "HEAD")) is None:
                reason = "not a git worktree"
            elif _git("status", "--porcelain", cwd=path).stdout.strip():
                reason = "it has uncommitted changes"
            elif _git("merge-base", "--is-ancestor", head, branch, cwd=root).returncode != 0:
                reason = f"its commit is not merged into {branch}"
            else:
                reason = None
            if reason:
                cat.skipped.append({"path": path, "reason": reason})
            else:
                cat.candidates.append(path)
    return cat


def fixed_category(key: str, label: str, paths: list[Path]) -> Category:
    return Category(key, label, [str(path) for path in paths], clearable=False)
