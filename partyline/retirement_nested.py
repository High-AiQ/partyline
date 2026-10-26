"""Conservative evidence for nested linked worktrees removed with a line."""

import os
import stat
import subprocess

from fastapi import HTTPException

from .git_fence import mirror_branch_ref, mirror_store
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


def nested_evidence(cwd, path, conv_id=None):
    """Accept attached worktrees matching their durable host or private mirror tip.

    Commits live in the owner's shared object store and survive removing the
    folder because a branch in the owning repository contains the inspected tip.
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
    branch = rev(full, "symbolic-ref", "-q", "HEAD")
    if not branch:
        refuse("detached HEAD")
    if not branch.startswith("refs/heads/"):
        refuse("no branch preserving HEAD in owning repository")
    name = branch.removeprefix("refs/heads/")
    head = rev(full, "rev-parse", "--verify", "HEAD")
    if not head:
        refuse("no branch preserving HEAD in owning repository")
    mirror_tip = mirror_branch_ref(full, conv_id, name) if conv_id else None
    store = mirror_store(os.path.dirname(owner), conv_id) if mirror_tip else None
    env = os.environ.copy()
    if mirror_tip:
        if not store:
            refuse("cannot inspect mirror tip")
        gitdir = rev(full, "rev-parse", "--absolute-git-dir")
        if not gitdir:
            refuse("cannot inspect status")
        env["GIT_DIR"] = store
        env["GIT_INDEX_FILE"] = os.path.join(gitdir, "index")
        env["GIT_WORK_TREE"] = full
        env["GIT_COMMON_DIR"] = store
        env["GIT_OBJECT_DIRECTORY"] = os.path.join(owner, "objects")
        if os.path.isdir(os.path.join(store, "objects")):
            env["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = os.path.join(store, "objects")

    def run(*args):
        try:
            return subprocess.run(["git", *args], cwd=full, env=env,
                                  capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError, UnicodeError):
            refuse("cannot inspect status")

    tip = mirror_tip or head
    # Compare both index and working files to the private tip. Host HEAD may
    # still name the start commit, making already committed files look staged.
    for args in (("diff", "--quiet", tip, "--"),
                 ("diff", "--cached", "--quiet", tip, "--")):
        result = run(*args)
        if result.returncode == 1:
            refuse("uncommitted edits beyond the mirror tip (dirty)" if mirror_tip else "dirty")
        if result.returncode:
            refuse("cannot inspect status")
    untracked = run("ls-files", "--others", "--exclude-standard", "-z")
    if untracked.returncode:
        refuse("cannot inspect status")
    if untracked.stdout:
        refuse("uncommitted edits beyond the mirror tip (dirty)" if mirror_tip else "dirty")
    if mirror_tip:
        # This command deliberately uses the owner's refs and objects, never
        # the private mirror: only a surviving local branch proves durability.
        branches = rev(owner, "for-each-ref", f"--contains={mirror_tip}",
                       "--format=%(refname)", "refs/heads/")
        if not branches:
            refuse("mirror tip not in the owning repository")
    elif not head or rev(owner, "rev-parse", "--verify", branch) != head:
        refuse("no branch preserving HEAD in owning repository")
    row = [path, "nested-worktree", head, name]
    return row + [mirror_tip] if mirror_tip else row
