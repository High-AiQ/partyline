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
import tempfile

from .git_fence_root import refresh as refresh_root_mirror

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


def _ensure_mirror_directory(path: str) -> None:
    """Ensure a mirror directory is not an attacker-controlled symlink."""
    if os.path.islink(path) or (os.path.lexists(path) and not os.path.isdir(path)):
        os.unlink(path)
    os.makedirs(path, exist_ok=True)


def _mirror_parent(root: str, rel: str) -> str:
    """Create a real directory path below ``root`` for one mirror entry."""
    _ensure_mirror_directory(root)
    current = root
    parts = rel.split(os.sep)[:-1]
    for part in parts:
        current = os.path.join(current, part)
        _ensure_mirror_directory(current)
    return current


def _replace_mirror_file(root: str, rel: str, write_file) -> None:
    """Write through a same-directory temporary and atomically replace the entry."""
    parent = _mirror_parent(root, rel)
    fd, temporary = tempfile.mkstemp(dir=parent)
    os.close(fd)
    try:
        write_file(temporary)
        os.replace(temporary, os.path.join(parent, os.path.basename(rel)))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _copy_to_mirror(src: str, root: str, rel: str) -> None:
    _replace_mirror_file(root, rel, lambda temporary: shutil.copy2(src, temporary))


def _write_mirror_text(root: str, rel: str, value: str) -> None:
    def write(temporary: str) -> None:
        with open(temporary, "w", encoding="utf-8") as file:
            file.write(value)

    _replace_mirror_file(root, rel, write)


def refresh_mirror(common: str, gitdir: str, conv_id: str) -> str:
    """Create or refresh the line's refs mirror; returns the mirror directory.

    Real refs and reflogs are copied in, except the worktree's own branch
    (and reflog), which the mirror keeps once it exists. Refs that exist
    only in the mirror — branches the line created — are kept as well.
    ``packed-refs`` is copied with the own-branch entry removed so the
    mirror's loose ref always wins.
    """
    mirror = _mirror_dir(common, conv_id)
    _ensure_mirror_directory(mirror)
    own = _head_branch(gitdir)
    for name in ("refs", "logs"):
        real_dir = os.path.join(common, name)
        mirror_dir = os.path.join(mirror, name)
        _ensure_mirror_directory(mirror_dir)
        if not os.path.isdir(real_dir):
            continue
        for rel in _walk_files(real_dir):
            mirror_file = os.path.join(mirror_dir, rel)
            if os.path.lexists(mirror_file):
                continue  # the mirror keeps what a previous launch wrote
            _copy_to_mirror(os.path.join(real_dir, rel), mirror_dir, rel)
        # Re-copy live sibling refs on every launch. The own branch and its
        # reflog are excluded: their mirror value is the line's committed
        # state, and the real copies never see the line's commits.
        keep = {own.removeprefix("refs/") if name == "refs" else own} if own else set()
        for rel in _walk_files(mirror_dir):
            if rel in keep:
                continue
            real_file = os.path.join(real_dir, rel)
            if os.path.isfile(real_file):
                _copy_to_mirror(real_file, mirror_dir, rel)
    # The own branch must exist loose in the mirror, or a real packed-refs
    # entry filtered below leaves the branch unresolvable.
    own_path = os.path.join(mirror, own) if own else None
    if own and (os.path.islink(own_path) or not os.path.isfile(own_path)):
        value = _read_ref(common, own)
        if value:
            _write_mirror_text(mirror, own, value + "\n")
    packed = os.path.join(common, "packed-refs")
    if os.path.isfile(packed):
        lines = []
        with open(packed, encoding="utf-8") as file:
            lines = file.readlines()
        if own:
            lines = [line for line in lines if not line.endswith(f" {own}\n")]
        _write_mirror_text(mirror, "packed-refs", "".join(lines))
    else:
        mirror_packed = os.path.join(mirror, "packed-refs")
        if os.path.islink(mirror_packed):
            os.unlink(mirror_packed)
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


def mirror_branch_ref(cwd: str, conv_id: str, branch: str) -> str | None:
    """The line's branch tip as its fence mirror holds it, when a mirror exists.

    A fenced line commits to the mirror branch, never the real ref, so an
    accept needs the mirror to tell the line's own work from a stray SHA.
    ``None``: not a linked worktree, no mirror on disk, or no ref in it.
    """
    gitdir = _worktree_gitdir(cwd)
    if gitdir is None:
        return None
    mirror = _mirror_dir(common_gitdir(gitdir), conv_id)
    if not os.path.isdir(mirror):
        return None
    return _read_ref(mirror, f"refs/heads/{branch}")


def darwin_write_paths(cwd: str) -> list[str]:
    """The writable git paths for one checkout on Darwin.

    macOS has no mount namespaces, so the mirror cannot be mounted and the
    fence falls back to the weaker Darwin guarantee (docs/write-fence.md):
    the worktree's own metadata directory and the repository's shared
    ``objects/``, ``refs/``, ``logs/``, and ``packed-refs`` are writable —
    sibling refs are writable there too — while ``config``, ``hooks``, and
    ``description`` are never named. A cwd that is not a linked worktree
    needs nothing: its ``.git`` is inside the tree it already writes.
    """
    gitdir = _worktree_gitdir(cwd)
    if gitdir is None:
        return []
    common = common_gitdir(gitdir)
    candidates = [gitdir, common]
    for name in ("objects", "refs", "logs"):
        candidates.append(os.path.join(common, name))
    candidates.append(os.path.join(common, "packed-refs"))
    return [path for path in candidates if os.path.lexists(path)]


def darwin_protected_git_paths(cwd: str) -> list[str]:
    """Git paths that stay protected when Darwin allows the common .git root."""
    gitdir = _worktree_gitdir(cwd)
    if gitdir is None:
        return []
    common = common_gitdir(gitdir)
    candidates = [os.path.join(common, name) for name in (
        "config", "hooks", "worktrees", "description", "HEAD", "info", "branches",
    )]
    return [path for path in candidates if os.path.lexists(path)]


def git_binds(cwd: str, conv_id: str) -> list[tuple[str, str, bool]]:
    """The git ``(host, guest, read_only)`` binds a fenced worktree line needs.

    Order is load-bearing: the private root mirror covers transient
    common-directory writes, real shared objects remain writable, real
    config/hooks/worktrees are protected, this worktree's metadata is
    reopened, then refs/logs/packed-refs are mirrored over their real
    paths.

    An empty list means the cwd is not a linked worktree and needs no git
    binds at all: a plain directory or a repository root whose ``.git`` is
    part of the tree the line may already write.
    """
    gitdir = _worktree_gitdir(cwd)
    if gitdir is None:
        return []
    common = common_gitdir(gitdir)
    mirror = refresh_mirror(common, gitdir, conv_id)
    refresh_root_mirror(common, mirror)
    binds = [
        (mirror, common, False),
        (os.path.join(common, "objects"), os.path.join(common, "objects"), False),
        (os.path.join(common, "hooks"), os.path.join(common, "hooks"), True),
        (os.path.join(common, "config"), os.path.join(common, "config"), True),
        (os.path.join(common, "worktrees"), os.path.join(common, "worktrees"), True),
        (gitdir, gitdir, False),
        (os.path.join(mirror, "refs"), os.path.join(common, "refs"), False),
    ]
    logs_mirror = os.path.join(mirror, "logs")
    binds.append((logs_mirror, os.path.join(common, "logs"), False))
    if os.path.isfile(os.path.join(mirror, "packed-refs")):
        binds.append((os.path.join(mirror, "packed-refs"),
                      os.path.join(common, "packed-refs"), False))
    return [bind for bind in binds if os.path.lexists(bind[0])]
