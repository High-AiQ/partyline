"""Conservative evidence for nested linked worktrees removed with a line."""

import os
import stat

from fastapi import HTTPException

from .line_worktree import rev


def file_kind(mode):
    for check, kind in ((stat.S_ISDIR, "directory"), (stat.S_ISFIFO, "fifo"),
                        (stat.S_ISSOCK, "socket"), (stat.S_ISCHR, "device"),
                        (stat.S_ISBLK, "device"), (stat.S_ISLNK, "symlink"),
                        (stat.S_ISREG, "file")):
        if check(mode):
            return kind
    return "unknown"


def linked_owner(full):
    """Return a registered linked worktree's shared Git directory, else None."""
    link = os.path.join(full, ".git")
    try:
        if os.path.islink(link) or not os.path.isfile(link):
            return None
        with open(link, encoding="utf-8") as stream:
            text = stream.read().strip()
        if not text.startswith("gitdir:"):
            return None
        gitdir = os.path.realpath(os.path.join(full, text[7:].strip()))
        if os.path.basename(os.path.dirname(gitdir)) != "worktrees":
            return None
        with open(os.path.join(gitdir, "gitdir"), encoding="utf-8") as stream:
            back = stream.read().strip()
        if os.path.realpath(os.path.join(gitdir, back)) != os.path.realpath(link):
            return None
        owner = rev(full, "rev-parse", "--path-format=absolute", "--git-common-dir")
        return os.path.realpath(owner) if owner else None
    except (OSError, UnicodeError):
        return None


def nested_evidence(cwd, path):
    """Accept only clean, attached worktrees with a durable owning branch.

    Commits live in the owner's shared object store and survive removing the
    folder because the owning repository retains the branch pointing to HEAD.
    The owner must be outside the folder retirement deletes and a different repo.
    """
    full = os.path.join(cwd, path)
    owner = linked_owner(full)
    if not owner:
        return None

    def refuse(reason):
        raise HTTPException(409, f"retirement nested-worktree {path}: {reason}")

    root = os.path.realpath(cwd)
    outer = rev(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if os.path.commonpath([root, owner]) == root or owner == os.path.realpath(outer or cwd):
        refuse("owning repository must survive outside the retiring folder")
    # rev returns None for both empty output and failures: inspect status explicitly.
    from .retirement_git import git
    try:
        dirty = git(full, "status", "--porcelain")
    except HTTPException:
        refuse("cannot inspect status")
    if dirty:
        refuse("dirty")
    branch = rev(full, "symbolic-ref", "-q", "HEAD")
    if not branch:
        refuse("detached HEAD")
    tip = rev(owner, "rev-parse", "--verify", branch)
    head = rev(full, "rev-parse", "--verify", "HEAD")
    if not branch.startswith("refs/heads/") or not tip or tip != head:
        refuse("no branch preserving HEAD in owning repository")
    return [path, "nested-worktree", head, branch.removeprefix("refs/heads/")]
