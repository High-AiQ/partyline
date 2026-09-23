"""The write fence: every attached process runs inside a platform sandbox
where only its line's declared write set is writable.

Why: a text brief does not bind a process. Whatever a line's worker is
told, the only durable boundary is the one the kernel enforces at
spawn time. The fence wraps the single place every pty process starts —
``adapters.base.Adapter.start`` — so no adapter can forget it.

The backend is chosen per platform at launch (``backend``): on Linux,
bubblewrap builds a mount namespace — ``/`` bound read-only, fresh
``/dev`` and ``/proc``, a private tmpfs over ``/tmp``, and each write-set
path bound writable at its real path. On Darwin, ``fence_darwin`` feeds
``sandbox-exec`` a generated profile that denies ``file-write*`` outside
the same write set (no mounts exist there, so git binds become the weaker
documented scope instead). The environment, the working directory, the
process group, and the network are kept as they were — this is a
filesystem fence, not a jail. A child line's Git needs are layered in by
``git_fence``: shared objects, a private copy-on-write mirror of refs,
and its own worktree metadata.

Failure is closed. If the platform's backend exists but cannot run — or
the platform has no backend at all — the process is refused, never
started unconfined. The attach route surfaces that as a 409 with the
reason, the platform, and the switch. The ``write_fence`` feature flag
exists so one restart cycle can turn the fence off in an emergency; the
default is on.

Extra scope is requested, never assumed: a line may be granted more by a
captain above it or by a person, and the grant is recorded on the line
(``conversation_write_grants``) and visible to the whole room.
"""

from __future__ import annotations

import os
import re
import sys

from . import features, fence_darwin, git_fence
from .line_worktree import REVIEW_DIR, repo_root

BWRAP = "/usr/bin/bwrap"

# Home directories every CLI may update: caches and tool configuration.
# Read access to everything else in the home stays, as everywhere else on
# the host — this fence bounds writes, not reads.
HOME_WRITE_PATHS = ("~/.cache", "~/.config")


class FenceUnavailable(RuntimeError):
    """The fence cannot be created; the process must not start unconfined."""


def bwrap_available() -> bool:
    return os.path.isfile(BWRAP) and os.access(BWRAP, os.X_OK)


def backend() -> str:
    """The fence backend this platform gets, decided at launch time:
    bubblewrap on Linux, Apple's sandbox-exec on Darwin, none elsewhere.
    """
    if sys.platform.startswith("linux"):
        return "bubblewrap"
    if sys.platform == "darwin":
        return "sandbox-exec"
    return "none"


def backend_available() -> tuple[bool, str]:
    """Whether the platform's backend can run, with a human-readable reason."""
    name = backend()
    if name == "bubblewrap":
        if bwrap_available():
            return True, ""
        return False, f"{BWRAP} is missing or not executable"
    if name == "sandbox-exec":
        if fence_darwin.sandbox_exec_available():
            return True, ""
        return False, f"{fence_darwin.SANDBOX_EXEC} is missing or not executable"
    return False, f"partyline ships no write-fence backend for platform '{sys.platform}'"


def _refusal(reason: str) -> str:
    """The fail-closed message: what is missing, the platform, and the one
    legitimate way out, named — the emergency flag, never a fallback.
    """
    return (f"{reason}; refusing to start an unconfined process "
            f"(platform {sys.platform}; for one emergency restart cycle the fence "
            f"can be switched off with PARTYLINE_FEATURE_WRITE_FENCE=0)")


def manifest_write_paths(att: dict) -> list[str]:
    """Home paths the adapter declares its CLI writes, from the manifest."""
    metadata = att.get("adapter_metadata") or {}
    return [os.path.expanduser(p) for p in (metadata.get("write_paths") or [])]


def existing(paths: list[str]) -> list[str]:
    """Bind sources must exist; a missing path grants nothing, so skip it."""
    return [p for p in paths if os.path.lexists(p)]


def _review_directory(cwd: str, *, create: bool = False) -> str | None:
    """Return the repository's real .review directory, creating it for a bind."""
    repo = repo_root(cwd)
    if repo is None:
        return None
    repo = os.path.realpath(repo)
    review_root = os.path.join(repo, REVIEW_DIR)
    if create and not os.path.lexists(review_root):
        try:
            os.mkdir(review_root)
        except FileExistsError:
            pass
        except OSError:
            return None
    if (not os.path.isdir(review_root) or os.path.islink(review_root) or
            os.path.realpath(review_root) != review_root):
        return None
    return review_root


def _review_worktree_paths(att: dict, review_root: str | None = None) -> list[str]:
    """Return recorded, canonical review checkouts for metadata binds only."""
    conv_id = att.get("conv_id")
    cwd = att.get("cwd") or ""
    rows = att.get("review_worktrees") or []
    repo = repo_root(cwd) if rows and conv_id else None
    if repo is None:
        return []
    repo = os.path.realpath(repo)
    expected_root = os.path.join(repo, REVIEW_DIR)
    review_root = review_root or _review_directory(cwd)
    if review_root != expected_root:
        return []

    paths = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("conv_id") != conv_id:
            continue
        sha, recorded = row.get("sha"), row.get("path")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
            continue
        expected = os.path.join(review_root, sha)
        if (not isinstance(recorded, str) or not os.path.isabs(recorded) or
                recorded != expected or os.path.islink(recorded) or
                os.path.realpath(recorded) != recorded or not os.path.isdir(recorded)):
            continue
        if (git_fence._worktree_gitdir(recorded) is None or
                os.path.realpath(repo_root(recorded) or "") != repo):
            continue
        paths.append(recorded)
    return paths


def _review_worktree_git_binds(path: str, cwd: str, conv_id: str) -> list[tuple[str, str, bool]]:
    """Git binds for a review worktree, skipped when its common .git is
    already inside the line's own cwd tree (the root captain's checkout):
    mounting a mirror over refs the line already owns writably would
    shadow branches and pulls made after spawn from ever being seen.
    """
    gitdir = git_fence._worktree_gitdir(path)
    if gitdir is not None:
        common = os.path.realpath(git_fence.common_gitdir(gitdir))
        cwd_real = os.path.realpath(cwd or "")
        if common == cwd_real or common.startswith(cwd_real + os.sep):
            return []
    return git_fence.git_binds(path, conv_id)


def write_set(att: dict, adapter_paths: list[str] | None = None) -> list[tuple[str, str, bool]]:
    """The ordered ``(host, guest, read_only)`` binds this attachment needs.

    ``adapter_paths`` comes from the adapter instance: paths only the
    running adapter knows, such as a per-attachment vendor home. A path
    already covered by an earlier bind is skipped, so a grant for a path
    inside the worktree or an adapter home cannot double-bind.
    """
    covered: set[str] = set()
    binds: list[tuple[str, str, bool]] = []

    def add(path: str) -> None:
        path = os.path.normpath(path)
        if path in covered or not os.path.lexists(path):
            return
        covered.add(path)
        binds.append((path, path, False))

    add(att.get("cwd") or "")
    for src, dst, read_only in git_fence.git_binds(att.get("cwd") or "",
                                                   att.get("conv_id") or ""):
        if src in covered:
            continue
        covered.add(src)
        binds.append((src, dst, read_only))
    review_root = _review_directory(att.get("cwd") or "", create=True)
    if review_root:
        add(review_root)
    for path in _review_worktree_paths(att, review_root):
        for src, dst, read_only in _review_worktree_git_binds(
                path, att.get("cwd") or "", att.get("conv_id") or ""):
            if src in covered:
                continue
            covered.add(src)
            binds.append((src, dst, read_only))
    for path in adapter_paths if adapter_paths is not None else manifest_write_paths(att):
        add(path)
    for grant in att.get("write_grants") or []:
        add(str(grant.get("path", "")))
    for path in HOME_WRITE_PATHS:
        add(os.path.expanduser(path))
    return binds


def darwin_write_set(att: dict, adapter_paths: list[str] | None = None) -> list[str]:
    """The writable paths for the sandbox-exec backend: the same scope as
    the bubblewrap write set, with git_fence's weaker Darwin scope in
    place of the mounts (docs/write-fence.md). Only paths that exist
    grant anything, as everywhere else.
    """
    paths: list[str] = []
    covered: set[str] = set()

    def add(path: str) -> None:
        if not path:
            return
        path = os.path.normpath(path)
        if path in covered or not os.path.lexists(path):
            return
        covered.add(path)
        paths.append(path)

    cwd = att.get("cwd") or ""
    add(cwd)
    for path in git_fence.darwin_write_paths(cwd):
        add(path)
    review_root = _review_directory(cwd, create=True)
    if review_root:
        add(review_root)
    for path in _review_worktree_paths(att, review_root):
        add(path)
        add(git_fence._worktree_gitdir(path) or "")
    for path in adapter_paths if adapter_paths is not None else manifest_write_paths(att):
        add(path)
    for grant in att.get("write_grants") or []:
        add(str(grant.get("path", "")))
    for path in HOME_WRITE_PATHS:
        add(os.path.expanduser(path))
    return paths


def _fence_args(att: dict) -> list[str]:
    return (att.get("adapter_metadata") or {}).get("fence_args") or []


def _bwrap_argv(att: dict, paths: list[str], command: list[str],
                tmpfs_tmp: bool) -> list[str]:
    argv = [BWRAP, "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc"]
    if tmpfs_tmp:
        argv += ["--tmpfs", "/tmp"]
    for src, dst, read_only in write_set(att, paths):
        argv += ["--ro-bind" if read_only else "--bind", src, dst]
    tail = list(command) + [flag for flag in _fence_args(att) if flag not in command]
    return argv + ["--die-with-parent", "--"] + tail


def launch_argv(adapter, tmpfs_tmp: bool = True) -> list[str]:
    """The argv to spawn for one adapter instance, through the platform's
    fence backend.

    ``fence_args`` from the manifest are appended to the command only
    when the fence is active: an adapter may declare argv that replaces a
    CLI-internal sandbox incompatible with the fence, because the fence
    itself is then the only sandbox the process has. A flag the command
    already carries is not appended again — CLIs reject a repeated flag.

    ``tmpfs_tmp`` exists for tests, which run their fixtures from paths
    under ``/tmp``: with the tmpfs on, bubblewrap recreates the bind
    destinations' directory chain inside the private tmpfs, and paths that
    are not bind destinations resolve to empty ghost directories rather
    than to the host files the assertions inspect. Production always
    mounts the private tmpfs; on Darwin there is no tmpfs and the flag
    has no equivalent to name.
    """
    command = adapter.build_command()
    if not features.enabled("write_fence"):
        return command
    available, reason = backend_available()
    if not available:
        raise FenceUnavailable(_refusal(reason))
    att = adapter.att
    hook = getattr(adapter, "write_paths", None)
    paths = manifest_write_paths(att) if hook is None else hook()
    if backend() == "sandbox-exec":
        return fence_darwin.argv(darwin_write_set(att, paths), command, _fence_args(att))
    return _bwrap_argv(att, paths, command, tmpfs_tmp)
