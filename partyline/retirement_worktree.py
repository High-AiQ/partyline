"""Keep worktree registrations until their directories have actually gone."""

import os
import shlex
import shutil
import subprocess
import tempfile

from fastapi import HTTPException

from .line_worktree import _git, rev
from .retirement_nested import linked_owner
from .worktree_paths import branch_name, managed_root


def refuse_orphan(root, path, branch=None):
    """Refuse a managed checkout whose registration no longer proves its state."""
    if not root or not os.path.isdir(path):
        return
    link = os.path.join(path, ".git")
    if not os.path.lexists(link) and not os.path.lexists(os.path.join(root, ".git")):
        return  # a plain task folder under a non-repository root
    try:
        listing = _git("worktree", "list", "--porcelain", "-z", cwd=root)
        registered = listing.returncode == 0 and f"worktree {path}\0" in listing.stdout
        common = rev(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
        valid = bool(common and linked_owner(path) == os.path.realpath(common)) if registered else False
    except (OSError, subprocess.SubprocessError):
        registered, valid = False, None
    if not registered or not valid:
        name = branch or branch_name(path)
        raise HTTPException(409, f"orphaned worktree {path}: preserve any uncommitted work and "
                            f"verify branch {name} is an ancestor of main; then run "
                            f"rm -rf {shlex.quote(path)}, git worktree prune, and "
                            f"git branch -d {shlex.quote(name)} in {root}")


def check_line(db, conv):
    from .task_workspaces import workspaces

    cwd = conv.get("cwd") or ""
    root = managed_root(cwd)
    refuse_orphan(root, cwd)
    for item in workspaces(db, conv.get("id") or ""):
        if item["path"] != cwd:
            refuse_orphan(item["repository"], item["path"], item["branch"])


def remove_directory(path, root):
    """Remove contents while the checkout remains registered, then move the empty shell."""
    if os.path.realpath(path) != path or os.path.realpath(root) != root:
        raise OSError("worktree paths must be canonical")
    link = os.path.join(path, ".git")
    common = rev(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not common or linked_owner(path) != os.path.realpath(common):
        raise OSError("worktree registration is missing or belongs to another repository")
    if not os.path.isfile(link) or os.path.islink(link):
        raise OSError("worktree Git link is missing or invalid")
    for entry in os.scandir(path):
        if entry.name == ".git":
            continue
        if entry.is_dir(follow_symlinks=False):
            shutil.rmtree(entry.path)
        else:
            os.unlink(entry.path)
    # The rename is atomic: before it the checkout and its Git link are in
    # place; after it the original directory is gone, so pruning is safe. The
    # moved shell contains only the link and can be discarded independently.
    holder = tempfile.mkdtemp(prefix=".partyline-removed-", dir=os.path.dirname(path))
    shell = os.path.join(holder, "worktree")
    try:
        os.rename(path, shell)
    except OSError:
        os.rmdir(holder)
        raise
    try:
        os.unlink(os.path.join(shell, ".git"))
        os.rmdir(shell)
        os.rmdir(holder)
    except OSError:
        pass  # only the empty shell/link remain; the original worktree is gone
