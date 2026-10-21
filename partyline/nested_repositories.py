"""Partyline never deletes a directory that contains a git repository of its own.

A task line once kept two separate clones inside its managed worktree; they were
ignored by the project repository, so ``git status`` called the worktree clean,
and ``git worktree remove --force`` deleted the clones with every commit that
existed nowhere else (`docs/lessons.md`). Every place that removes a worktree or
checkout asks here first: a directory holding a nested repository is kept, counts
as not clean, and is named in the result. ``discard`` does not waive it.
"""

import logging
import os
import subprocess

logger = logging.getLogger(__name__)

SKIP = frozenset({"node_modules"})
MAX_DEPTH = 8


def clean_worktree(directory: str) -> bool:
    """A git worktree of another clone (its `.git` file points back at it) with nothing uncommitted."""
    link = os.path.join(directory, ".git")
    try:
        if os.path.islink(link) or not os.path.isfile(link):
            return False
        with open(link, encoding="utf-8") as file:
            text = file.read().strip()
        gitdir = text.removeprefix("gitdir:").strip()
        with open(os.path.join(gitdir, "gitdir"), encoding="utf-8") as file:
            back = file.read().strip()
        registered = os.path.basename(os.path.dirname(gitdir)) == "worktrees"
        if not registered or os.path.realpath(back) != os.path.realpath(link):
            return False
        done = subprocess.run(["git", "status", "--porcelain"], cwd=directory, capture_output=True,
                              text=True, timeout=30)
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return False
    return done.returncode == 0 and not done.stdout.strip()


def nested_repositories(path: str, max_depth: int = MAX_DEPTH, skip: frozenset = SKIP,
                        lenient: bool = False) -> list[str]:
    """Every directory under ``path`` holding a ``.git`` (directory or file), relative.

    ``lenient`` leaves out a clean, registered worktree of a clone: its commits live in that
    clone, and a task's workspace is removed through git (`task_teardown`). The path's own
    ``.git`` is not nested. Ignored files count; ``node_modules`` is skipped,
    a repository is reported and not entered, and the walk stops ``max_depth`` levels down.
    """
    found: list[str] = []

    def walk(directory: str, depth: int) -> None:
        if directory != path and os.path.lexists(os.path.join(directory, ".git")):
            if not (lenient and clean_worktree(directory)):
                found.append(os.path.relpath(directory, path))
            return
        try:
            entries = list(os.scandir(directory))
        except OSError:
            return
        for entry in entries:
            if (depth < max_depth and entry.name not in skip and entry.name != ".git"
                    and entry.is_dir(follow_symlinks=False)):
                walk(entry.path, depth + 1)

    walk(path, 0)
    return sorted(found)


def keep_reason(path: str, lenient: bool = False) -> str | None:
    """``kept <path>: contains repositories …`` when ``path`` must not be deleted, else None."""
    if not os.path.isdir(path):
        return None
    nested = nested_repositories(path, lenient=lenient)
    if not nested:
        return None
    reason = f"kept {path}: contains repositories {', '.join(nested)}"
    logger.warning(reason)
    return reason
