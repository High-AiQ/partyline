"""Git confinement for a fenced worktree line.

A child line's worktree is writable by design, but a worktree's Git
metadata lives in the parent repository's ``.git`` directory, shared with
every sibling line and the person's checkout. Binding that directory
writable would let one line rewrite a sibling's branch, the repo config,
or its hooks — so the fence shares only what commits genuinely need:

- ``objects/`` — content-addressed and immutable once written; shared and
  writable, because the commit a line hands its captain must exist in the
  real object store or the accept fast-forward cannot find it.
- ``refs/``, ``logs/``, ``packed-refs`` — served as a private copy-on-write
  mirror mounted over the real paths. The process reads fresh sibling refs
  and commits to its own branch freely, but every write lands in the
  mirror; the real repository is never bound writable, so sibling branch
  refs, reflogs, and packed refs are physically immutable no matter what
  the process does.
- ``worktrees/`` — read-only, except the line's own metadata directory,
  which holds this worktree's HEAD and index.
- everything else (``config``, ``hooks``, ``description``) — never bound,
  so the ``/`` read-only bind keeps them immutable.

The mirror is refreshed on every launch: real refs are copied in, except
the line's own branch and any ref the line created, which the mirror
keeps. A commit therefore survives the process restart that a resume
needs, while sibling refs stay current enough for ordinary work.
"""

from __future__ import annotations

import hashlib
import os
import shutil

# Mirror state lives beside the other per-attachment session state.
FENCE_ROOT = os.path.expanduser("~/.partyline/sessions/fence")


def _worktree_gitdir(cwd: str) -> str | None:
    """The ``.git/worktrees/<name>`` directory a worktree's gitdir file names."""
    link = os.path.join(cwd, ".git")
    if not os.path.isfile(link):
        return None
    try:
        with open(link, encoding="utf-8") as file:
            text = file.read().strip()
    except OSError:
        return None
    if not text.startswith("gitdir:"):
        return None
    gitdir = text[len("gitdir:"):].strip()
    if not os.path.isdir(gitdir) or os.path.basename(os.path.dirname(gitdir)) != "worktrees":
        return None
    return gitdir


def common_gitdir(gitdir: str) -> str:
    """The shared ``.git`` directory: the parent of ``worktrees/<name>``."""
    return os.path.dirname(os.path.dirname(gitdir))


def _head_branch(gitdir: str) -> str | None:
    """``refs/heads/<branch>`` this worktree's HEAD names, if any."""
    try:
        with open(os.path.join(gitdir, "HEAD"), encoding="utf-8") as file:
            text = file.read().strip()
    except OSError:
        return None
    return text[len("ref: "):] if text.startswith("ref: ") else None


def _mirror_dir(common: str, conv_id: str) -> str:
    key = hashlib.sha256(common.encode()).hexdigest()[:16]
    return os.path.join(FENCE_ROOT, conv_id or "line", f"git-{key}")


def _copy_tree(src: str, dst: str) -> None:
    shutil.copytree(src, dst, dirs_exist_ok=True)


def _walk_files(root: str) -> list[str]:
    found = []
    for base, _dirs, names in os.walk(root):
        for name in names:
            path = os.path.join(base, name)
            found.append(os.path.relpath(path, root))
    return sorted(found)


def refresh_mirror(common: str, gitdir: str, conv_id: str) -> str:
    """Create or refresh the line's refs mirror; returns the mirror directory.

    Real refs and reflogs are copied in, except the worktree's own branch
    (and reflog), which the mirror keeps once it exists. Refs that exist
    only in the mirror — branches the line created — are kept as well.
    ``packed-refs`` is copied with the own-branch entry removed so the
    mirror's loose ref always wins.
    """
    mirror = _mirror_dir(common, conv_id)
    own = _head_branch(gitdir)
    for name in ("refs", "logs"):
        real_dir = os.path.join(common, name)
        mirror_dir = os.path.join(mirror, name)
        os.makedirs(mirror_dir, exist_ok=True)
        if not os.path.isdir(real_dir):
            continue
        for rel in _walk_files(real_dir):
            mirror_file = os.path.join(mirror_dir, rel)
            if os.path.lexists(mirror_file):
                continue  # the mirror keeps what a previous launch wrote
            os.makedirs(os.path.dirname(mirror_file), exist_ok=True)
            shutil.copy2(os.path.join(real_dir, rel), mirror_file)
        # Re-copy live sibling refs on every launch. The own branch and its
        # reflog are excluded: their mirror value is the line's committed
        # state, and the real copies never see the line's commits.
        keep = {os.path.relpath(own, name)} if own else set()
        for rel in _walk_files(mirror_dir):
            if rel in keep:
                continue
            real_file = os.path.join(real_dir, rel)
            if os.path.isfile(real_file):
                shutil.copy2(real_file, os.path.join(mirror_dir, rel))
    # The own branch must exist loose in the mirror, or a real packed-refs
    # entry filtered below leaves the branch unresolvable.
    if own and not os.path.isfile(os.path.join(mirror, own)):
        value = _read_ref(common, own) or _read_ref(mirror, own)
        if value:
            path = os.path.join(mirror, own)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as file:
                file.write(value + "\n")
    packed = os.path.join(common, "packed-refs")
    if os.path.isfile(packed):
        lines = []
        with open(packed, encoding="utf-8") as file:
            lines = file.readlines()
        if own:
            lines = [line for line in lines if not line.endswith(f" {own}\n")]
        with open(os.path.join(mirror, "packed-refs"), "w", encoding="utf-8") as file:
            file.writelines(lines)
    return mirror


def _read_ref(root: str, ref: str) -> str | None:
    """The value of one loose or packed ref under ``root``."""
    try:
        with open(os.path.join(root, ref), encoding="utf-8") as file:
            return file.read().strip()
    except OSError:
        pass
    try:
        with open(os.path.join(root, "packed-refs"), encoding="utf-8") as file:
            for line in file:
                if line.endswith(f" {ref}\n"):
                    return line.split(" ", 1)[0].strip()
    except OSError:
        return None
    return None


def git_binds(cwd: str, conv_id: str) -> list[tuple[str, str, bool]]:
    """The git ``(host, guest, read_only)`` binds a fenced worktree line needs.

    Order is load-bearing: the shared ``worktrees/`` tree is bound
    read-only after the writable binds that need to shadow it, and the
    line's own metadata directory is bound writable after that, so the
    last word on each path is the right one.

    An empty list means the cwd is not a linked worktree and needs no git
    binds at all: a plain directory or a repository root whose ``.git`` is
    part of the tree the line may already write.
    """
    gitdir = _worktree_gitdir(cwd)
    if gitdir is None:
        return []
    common = common_gitdir(gitdir)
    mirror = refresh_mirror(common, gitdir, conv_id)
    binds = [
        (os.path.join(common, "objects"), os.path.join(common, "objects"), False),
        (os.path.join(mirror, "refs"), os.path.join(common, "refs"), False),
    ]
    logs_mirror = os.path.join(mirror, "logs")
    os.makedirs(logs_mirror, exist_ok=True)
    binds.append((logs_mirror, os.path.join(common, "logs"), False))
    if os.path.isfile(os.path.join(mirror, "packed-refs")):
        binds.append((os.path.join(mirror, "packed-refs"),
                      os.path.join(common, "packed-refs"), False))
    binds.append((os.path.join(common, "worktrees"),
                  os.path.join(common, "worktrees"), True))
    binds.append((gitdir, gitdir, False))
    return binds
