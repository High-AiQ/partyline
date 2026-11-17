"""Shared removal for disposable review and scratch checkouts."""

import logging
import os
import shutil

from .nested_repositories import keep_reason
from .retirement_errors import git_reason, operation_reason, safe_text
from .worktree_recovery import remove_registration

logger = logging.getLogger(__name__)


def remove_checkout(path, directory, *, git, fallback, errors=None):
    """Remove one managed checkout and optionally collect safe refusal reasons."""
    marker = f"/{directory}/"
    if not os.path.isdir(path):
        if marker in path:
            remove_registration(path.split(marker, 1)[0], path)
        return True
    if reason := keep_reason(path):
        if errors is not None:
            errors.append(safe_text(reason))
        return False
    root = path.split(marker, 1)[0] if marker in path else None
    failure = ""
    if root and os.path.isdir(root):
        done = git("worktree", "remove", "--force", "--force", path, cwd=root)
        if done.returncode == 0:
            return True
        failure = git_reason(done)
        logger.warning("auxiliary worktree prune: git refused to remove %s", path)
        if not fallback:
            if errors is not None:
                errors.append(failure)
            return False
    try:
        shutil.rmtree(path)
    except OSError as exc:
        failure = operation_reason(exc)
    removed = not os.path.isdir(path)
    if not removed and errors is not None:
        errors.append(failure or "worktree directory could not be removed")
    return removed
