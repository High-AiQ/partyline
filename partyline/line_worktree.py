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
import tempfile

from .hierarchy import lead_attachment, parent_id_of

WORKTREES_DIR = ".partyline-worktrees"
REVIEW_DIR = ".review"
_GIT_TIMEOUT = 30


def _git(*args: str, cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=_GIT_TIMEOUT
    )


def rev(cwd: str, *args: str) -> str | None:
    """Run git read-only and return its stripped stdout, or None on any failure."""
    try:
        done = _git(*args, cwd=cwd)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None


def repo_and_worktree(cwd: str) -> tuple[str | None, str | None]:
    """The repository root and the line's worktree, when that still exists.

    A placed line is recognised by its worktree path, so a worktree removed
    after an archive still names both sides; a line in a shared checkout is
    its own worktree.
    """
    cwd = (cwd or "").rstrip("/")
    if f"/{WORKTREES_DIR}/" in cwd:
        root = cwd.split(f"/{WORKTREES_DIR}/", 1)[0]
        if not os.path.isdir(root):
            return None, None
        return root, cwd if os.path.isdir(cwd) else None
    if not cwd or not os.path.isdir(cwd):
        return None, None
    return repo_root(cwd), cwd


def repo_root(path: str | None) -> str | None:
    """The repository's main working tree, even when ``path`` is inside one of
    its linked worktrees. Children of a child line otherwise nested their
    worktrees inside the parent's — ``.partyline-worktrees/a/.partyline-worktrees/b``
    — and a long project grew a directory for every generation."""
    if not path or not os.path.isdir(path):
        return None
    try:
        done = _git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=path)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0 or not done.stdout.strip():
        return None
    common = done.stdout.strip()
    return os.path.dirname(common) if os.path.basename(common) == ".git" else common


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


def _exclude(root: str, name: str = WORKTREES_DIR) -> None:
    """Keep a partyline-managed directory out of the repository's status output."""
    info = os.path.join(root, ".git", "info")
    try:
        os.makedirs(info, exist_ok=True)
        exclude = os.path.join(info, "exclude")
        existing = open(exclude).read() if os.path.exists(exclude) else ""
        if f"{name}/" not in existing:
            with open(exclude, "a") as fh:
                fh.write(f"\n{name}/\n")
    except OSError:
        pass  # a bare or read-only .git: status noise is not worth failing for


def project_directory(path: str) -> bool:
    """A directory it is sane to turn into a repository: somewhere under the
    user's home, not the home itself, and not a system or temporary tree.
    The test fixtures' ``/tmp`` would otherwise have been git-initialised."""
    real = os.path.realpath(path)
    home = os.path.realpath(os.path.expanduser("~"))
    tmp = os.path.realpath(tempfile.gettempdir())
    inside_home = real.startswith(home + os.sep)
    return inside_home and not real.startswith(tmp + os.sep) and real != tmp


def init_repo(path: str | None) -> str | None:
    """Turn a plain working directory into a repository so children can branch.

    A project started in a blank directory otherwise hands every child line
    the same directory, and captains spend their turns coordinating writes.
    One empty root commit is enough for ``git worktree add`` to branch from.
    """
    if not path or not os.path.isdir(path) or not os.access(path, os.W_OK):
        return None
    if not project_directory(path):
        return None
    try:
        if _git("init", "-q", "-b", "main", cwd=path).returncode != 0:
            return None
        done = _git("-c", "user.name=partyline", "-c", "user.email=partyline@localhost",
                    "commit", "-q", "--allow-empty", "-m", "line root", cwd=path)
        return path if done.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def placement_root(repository: str | None) -> tuple[str | None, str | None]:
    """The repository root a child is placed into, and why it may not be.

    An explicit ``repository`` — an absolute path anywhere inside a git
    repository this machine has — sends the child to that repository's
    ``.partyline-worktrees``; work that belongs to another project is placed
    there instead of being born in whatever checkout the parent line happens
    to sit in. The default — no ``repository`` — is ``(None, None)``: the
    caller falls back to the parent line's own repository, which a plain
    directory is initialised into as before. An explicit repository is never
    initialised: a path that is not inside a git repository is refused.
    """
    if not repository:
        return None, None
    repo = repository.strip()
    if not os.path.isabs(repo):
        return None, "repository must be an absolute path to a git repository"
    root = repo_root(repo)
    if root is None:
        return None, f"{repo} is not inside a git repository"
    return root, None


def place_child(
    db, parent_id: str, child_id: str, base: str | None = None, root: str | None = None,
) -> dict:
    """Give a new child line its working directory; record and describe it.

    Returns ``{"cwd": path or None, "branch": name or None, "base": ref or None}``.
    ``base`` is an explicit start point (an upstream ref) for a deliberate cut
    from a checkout left behind; the default stays the repository's HEAD.
    ``root`` overrides the repository the worktree is placed in (another
    project on this machine); the default is the parent line's repository.
    """
    parent_cwd = line_cwd(db, parent_id)
    if root is None:
        root = repo_root(parent_cwd) or init_repo(parent_cwd)
    placed = {"cwd": parent_cwd, "branch": None, "base": None}
    if root is not None:
        child = db.get_conversation(child_id) or {}
        name = slug(child.get("name") or child_id)
        path = _free_path(os.path.join(root, WORKTREES_DIR, name))
        branch = f"line/{os.path.basename(path)}"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _exclude(root)
        if base:
            done = _git("worktree", "add", "-b", branch, path, base, cwd=root)
        else:
            done = _git("worktree", "add", "-b", branch, path, cwd=root)
        if done.returncode != 0:  # the branch exists: put the worktree on it
            done = _git("worktree", "add", path, branch, cwd=root)
        if done.returncode == 0:
            placed = {"cwd": path, "branch": branch, "base": base}
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
    if placed.get("base"):
        where += f"; cut from {placed['base']} after a fetch, not from the parent's checkout"
    return where

