"""A task's workspace: one git worktree per repository under the root captain's folder.

A person starts the root in a parent folder whose subfolders are separate clones
(a frontend, a backend, sometimes the folder is a repository too), and a task
edits several of them. The task folder is ``<root folder>/.partyline-worktrees/<slug>``:
a worktree of the root folder when that is a repository, a plain folder otherwise,
and a worktree of each nested clone at the same relative path, every one on
``line/<slug>`` in its own real clone. Commits are objects in the real clone;
the branch ref stays in the process's private mirror until accept, so
``anchor`` keeps a hidden real ref that git's gc can see.
"""

from __future__ import annotations

import os
import shutil

from .git_fence import mirror_branch_ref
from .line_worktree import WORKTREES_DIR, _exclude, _git, line_cwd, repo_root, rev, slug
from .nested_repositories import SKIP, nested_repositories
from .worktree_paths import branch_name

SCAN_DEPTH = 3
SCAN_SKIP = SKIP | {WORKTREES_DIR, ".review", ".scratch"}
ANCHOR = "refs/partyline/tasks"
GUIDES = ("AGENTS.md", "CLAUDE.md")


def workspaces(db, conv_id: str) -> list[dict]:
    rows = db._exec("SELECT * FROM task_workspaces WHERE conv_id=? ORDER BY rowid",
                    (conv_id,)).fetchall()
    return [dict(row) for row in rows]


def repositories_under(folder: str) -> list[str]:
    """The repository the folder is, then every clone under it (depth <= 3), absolute."""
    base = repo_root(folder) if os.path.lexists(os.path.join(folder, ".git")) else None
    found = [base] if base else []
    found += [os.path.join(folder, rel) for rel in nested_repositories(folder, SCAN_DEPTH, SCAN_SKIP)]
    return found


def _free(repos: list[str], folder: str, name: str) -> bool:
    return not os.path.exists(os.path.join(folder, WORKTREES_DIR, name)) and not any(
        _git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch_name(name)}",
             cwd=repo).returncode == 0 for repo in repos)


def _add(repo: str, path: str, branch: str) -> bool:
    return _git("worktree", "add", "-b", branch, path, cwd=repo).returncode == 0


def place_task(db, root_id: str, conv_id: str) -> dict | None:
    """Create the task's workspace, or None when the root folder holds no repository."""
    folder = line_cwd(db, root_id)
    top = repo_root(folder) if folder else None
    folder = top or folder
    if not folder or not os.path.isdir(folder):
        return None
    repos = repositories_under(folder)
    if not repos:
        return None
    base = slug((db.get_conversation(conv_id) or {}).get("name") or conv_id)
    name, n = base, 1
    while not _free(repos, folder, name):
        n += 1
        name = f"{base}-{n}"
    task_dir = os.path.join(folder, WORKTREES_DIR, name)
    branch = branch_name(task_dir)
    os.makedirs(os.path.dirname(task_dir), exist_ok=True)
    plain = top is None
    if plain:
        os.makedirs(task_dir)
        for guide in GUIDES:  # the root's guidance, linked: nothing ever writes through it
            if os.path.isfile(os.path.join(folder, guide)):
                os.symlink(os.path.join(folder, guide), os.path.join(task_dir, guide))
    made: list[tuple[str, str, str]] = []
    for repo in repos:
        nested = os.path.realpath(repo) != os.path.realpath(folder)
        where = os.path.join(task_dir, os.path.relpath(repo, folder)) if nested else task_dir
        if nested and not plain:
            _exclude(folder, os.path.relpath(repo, folder))
        head = rev(repo, "rev-parse", "HEAD")
        if not (head and _add(repo, where, branch)):
            for done, path, _head in reversed(made):
                _git("worktree", "remove", "--force", path, cwd=done)
                _git("branch", "-D", branch, cwd=done)
            if plain:
                shutil.rmtree(task_dir, ignore_errors=True)
            return None
        made.append((repo, where, head))
    for repo, where, head in made:
        db._exec("INSERT INTO task_workspaces(conv_id,repository,path,branch,base_sha) "
                 "VALUES(?,?,?,?,?)", (conv_id, repo, where, branch, head))
    db._exec("UPDATE conversations SET cwd=? WHERE id=?", (task_dir, conv_id))
    return {"cwd": task_dir, "branch": branch, "base": None, "plain": plain,
            "workspaces": [repo for repo, _w, _h in made]}


def describe(placed: dict) -> str:
    where = f"☏ working directory: {placed['cwd']}"
    if placed["plain"]:
        where += " — a folder of git worktrees, one per repository under the root's folder"
    else:
        where += " — a git worktree, with a worktree of each repository nested under the root's folder"
    return (where + f"; every repository has branch {placed['branch']} (commit in the one you "
            "changed); request_review with no arguments reviews each that moved. Repositories: "
            + ", ".join(placed["workspaces"]))


def tip(workspace: dict, conv_id: str) -> str | None:
    """The workspace's branch tip: the process's mirror ref when it has one, else the real ref."""
    return (mirror_branch_ref(workspace["path"], conv_id, workspace["branch"])
            or rev(workspace["repository"], "rev-parse", "--verify", "--quiet",
                   f"refs/heads/{workspace['branch']}"))


def moved(db, conv_id: str) -> list[tuple[str, str]]:
    """``(repository, tip)`` for each workspace whose branch moved past its base."""
    found = []
    for item in workspaces(db, conv_id):
        head = tip(item, conv_id)
        if head and head != item["base_sha"]:
            found.append((item["repository"], head))
    return found


def anchor(db, conv_id: str) -> None:
    """Keep every workspace tip reachable from a hidden ref in its real clone.

    The tip is otherwise only a ref in the process's private mirror, which git's
    gc in the real clone cannot see; objects reachable from nothing are pruned.
    """
    for item in workspaces(db, conv_id):
        head = tip(item, conv_id)
        if head and head != item["base_sha"] and rev(
                item["repository"], "rev-parse", "--verify", "--quiet", f"{head}^{{commit}}"):
            _git("update-ref", f"{ANCHOR}/{item['branch'].removeprefix('line/')}", head,
                 cwd=item["repository"])
