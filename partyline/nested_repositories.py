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

logger = logging.getLogger(__name__)

SKIP = frozenset({"node_modules"})
MAX_DEPTH = 8


def nested_repositories(path: str, max_depth: int = MAX_DEPTH) -> list[str]:
    """Every directory under ``path`` holding a ``.git`` (directory or file), relative.

    The path's own ``.git`` is not nested. Ignored files count; ``node_modules`` is skipped,
    a repository is reported and not entered, and the walk stops ``max_depth`` levels down.
    """
    found: list[str] = []

    def walk(directory: str, depth: int) -> None:
        if directory != path and os.path.lexists(os.path.join(directory, ".git")):
            found.append(os.path.relpath(directory, path))
            return
        try:
            entries = list(os.scandir(directory))
        except OSError:
            return
        for entry in entries:
            if (depth < max_depth and entry.name not in SKIP and entry.name != ".git"
                    and entry.is_dir(follow_symlinks=False)):
                walk(entry.path, depth + 1)

    walk(path, 0)
    return sorted(found)


def keep_reason(path: str) -> str | None:
    """``kept <path>: contains repositories …`` when ``path`` must not be deleted, else None."""
    if not os.path.isdir(path):
        return None
    nested = nested_repositories(path)
    if not nested:
        return None
    reason = f"kept {path}: contains repositories {', '.join(nested)}"
    logger.warning(reason)
    return reason
