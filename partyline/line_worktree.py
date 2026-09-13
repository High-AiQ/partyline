"""Every child line works in its own git worktree of the parent's repository.

Two lines editing one checkout is the hazard that no amount of prose closed:
a child line's worker had forty uncommitted files in a checkout when a
sibling process on the root line was one tool call from editing on top of
them. So a child line is placed when it is born. If the parent line's
working directory is inside a git repository, the child gets
``<repo>/.partyline-worktrees/<slug>`` on branch ``line/<slug>``, and every
process attached to that line runs there; a machine cannot choose another
directory. Otherwise the child inherits the parent's directory. The worktree
starts from the repository's HEAD: the parent's uncommitted changes are not
in it, which is the point — its captain accepts the branch, not a diff.
"""

from __future__ import annotations

import os
import re
import subprocess

from .hierarchy import lead_attachment, parent_id_of

WORKTREES_DIR = ".partyline-worktrees"
_GIT_TIMEOUT = 30


def _git(*args: str, cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=_GIT_TIMEOUT
    )


def repo_root(path: str | None) -> str | None:
    if not path or not os.path.isdir(path):
        return None
    try:
        done = _git("rev-parse", "--show-toplevel", cwd=path)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() or None if done.returncode == 0 else None


def line_cwd(db, conv_id: str) -> str | None:
    """Where a line works: its own directory, else its captain's, else any
    process's, else its parent line's. Never the server's own directory: a
    child born before placement existed put its first workers in the deployed
    checkout that way."""
    conv = db.get_conversation(conv_id) or {}
    if conv.get("cwd"):
        return conv["cwd"]
    lead = lead_attachment(db, conv_id)
    if lead is not None and lead.get("cwd"):
        return lead["cwd"]
    rows = db.list_attachments(conv_id)
    live = [att for att in rows if att["status"] in ("starting", "running")]
    for att in live + rows:
        if att.get("cwd"):
            return att["cwd"]
    parent = parent_id_of(conv)
    return line_cwd(db, parent) if parent else None


def ensure_placed(db, conv_id: str) -> dict | None:
    """Place a child line that was born before placement existed, on its
    first machine attach; returns the placement when one was made."""
    conv = db.get_conversation(conv_id) or {}
    parent = parent_id_of(conv)
    if conv.get("cwd") or not parent or db.list_attachments(conv_id):
        return None
    return place_child(db, parent, conv_id)


def slug(name: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-.").lower()
    return text[:48] or "line"


def _free_path(base: str) -> str:
    path, n = base, 1
    while os.path.exists(path):
        n += 1
        path = f"{base}-{n}"
    return path


def _exclude(root: str) -> None:
    """Keep the worktree directory out of the repository's status output."""
    info = os.path.join(root, ".git", "info")
    try:
        os.makedirs(info, exist_ok=True)
        exclude = os.path.join(info, "exclude")
        existing = open(exclude).read() if os.path.exists(exclude) else ""
        if f"{WORKTREES_DIR}/" not in existing:
            with open(exclude, "a") as fh:
                fh.write(f"\n{WORKTREES_DIR}/\n")
    except OSError:
        pass  # a bare or read-only .git: status noise is not worth failing for


def place_child(db, parent_id: str, child_id: str) -> dict:
    """Give a new child line its working directory; record and describe it.

    Returns ``{"cwd": path or None, "branch": name or None}``.
    """
    parent_cwd = line_cwd(db, parent_id)
    root = repo_root(parent_cwd)
    placed = {"cwd": parent_cwd, "branch": None}
    if root is not None:
        child = db.get_conversation(child_id) or {}
        name = slug(child.get("name") or child_id)
        path = _free_path(os.path.join(root, WORKTREES_DIR, name))
        branch = f"line/{os.path.basename(path)}"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _exclude(root)
        done = _git("worktree", "add", "-b", branch, path, cwd=root)
        if done.returncode != 0:  # the branch exists: put the worktree on it
            done = _git("worktree", "add", path, branch, cwd=root)
        if done.returncode == 0:
            placed = {"cwd": path, "branch": branch}
    if placed["cwd"]:
        db._exec("UPDATE conversations SET cwd=? WHERE id=?", (placed["cwd"], child_id))
    return placed


def describe(placed: dict) -> str | None:
    if not placed.get("cwd"):
        return None
    where = f"☏ working directory: {placed['cwd']}"
    if placed.get("branch"):
        where += (f" — a git worktree on branch {placed['branch']}; every process on this "
                  "line works here, and the branch is what the parent accepts")
    return where


def remove_for_line(conv: dict | None) -> None:
    """Drop the worktree a purged line was placed in; its branch stays."""
    cwd = (conv or {}).get("cwd") or ""
    if f"/{WORKTREES_DIR}/" not in cwd or not os.path.isdir(cwd):
        return
    root = cwd.split(f"/{WORKTREES_DIR}/")[0]
    try:
        _git("worktree", "remove", "--force", cwd, cwd=root)
    except (OSError, subprocess.SubprocessError):
        pass
