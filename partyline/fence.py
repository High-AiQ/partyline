"""The write fence: every attached process runs inside a platform sandbox
where a protected set — every managed repository and the partyline
database — is read-only, and everything else is writable.

Why: a text brief does not bind a process. Whatever a line's worker is
told, the only durable boundary is the one the kernel enforces at
spawn time. The fence wraps the single place every pty process starts —
``adapters.base.Adapter.start`` — so no adapter can forget it.

The backend is chosen per platform at launch (``backend``): on Linux,
bubblewrap builds a mount namespace — ``/`` bound writable, a full
``/dev`` and ``/proc`` pass through, then every protected repository root
bound read-only, then this line's own
worktree, metadata, review area, and git objects/mirror bound writable
again on top. On Darwin, ``fence_darwin`` feeds ``sandbox-exec`` a
generated profile that denies ``file-write*`` under the protected roots
and the database, then re-allows it under the same carve-outs (no mounts
exist there, so git binds become the weaker documented scope instead).
The environment, the working directory, the process group, and the
network are kept as they were — this is a filesystem fence, not a jail.
A child line's Git needs are layered in by ``git_fence``: shared objects,
a private copy-on-write mirror of refs, and its own worktree metadata.

The protected set is computed fresh at spawn from the database
(``fence_protect.protected_repo_roots``): every non-archived line's
repository root, plus the database file and its sidecars. A repository
not yet known to partyline is therefore writable — a documented
consequence of deriving the set this way. A line whose own ``cwd`` is a
repository's root (the root captain, in the person's checkout) is exempt
from its own repository's protection and keeps that checkout writable,
exactly as before the fence was inverted.

Failure is closed. If the platform's backend exists but cannot run — or
the platform has no backend at all — the process is refused, never
started unconfined. The attach route surfaces that as a 409 with the
reason, the platform, and the switch. The ``write_fence`` feature flag
exists so one restart cycle can turn the fence off in an emergency; the
default is on.

Extra scope is requested, never assumed: a line may be granted more by a
captain above it or by a person, and the grant is recorded on the line
(``conversation_write_grants``), bound writable last so it can restore
access even under a protected root, and visible to the whole room.
"""

from __future__ import annotations

import os
import sys

from . import features, fence_darwin, fence_protect, git_fence
from .fence_paths import darwin_write_set, write_set

BWRAP = "/usr/bin/bwrap"
DEV_ROOT = "/dev"


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


def _refusal(reason: str, remedy: str = "") -> str:
    """Describe the probe failure and the person-side remedy for an attach 409."""
    if not remedy:
        from .fence_probe import remedy as install_remedy

        remedy = install_remedy()
    advice = f" Remedy: {remedy}" if remedy else ""
    return f"{reason}.{advice}"


def existing(paths: list[str]) -> list[str]:
    """Bind sources must exist; a missing path grants or protects nothing."""
    return [p for p in paths if os.path.lexists(p)]


def _grant_paths(att: dict) -> list[str]:
    return existing([str(grant.get("path", "")) for grant in att.get("write_grants") or []])


def _protected_roots(att: dict) -> list[str]:
    """This attachment's protected repository roots, minus its own — a root
    captain's checkout is exempt from its own repository's protection."""
    own = fence_protect.own_repo_root(att.get("cwd") or "")
    return [root for root in existing(att.get("protected_roots") or []) if root != own]


def _fence_args(att: dict) -> list[str]:
    return (att.get("adapter_metadata") or {}).get("fence_args") or []


def _bwrap_argv(att: dict, command: list[str]) -> list[str]:
    argv = [BWRAP, "--bind", "/", "/", "--dev-bind", DEV_ROOT, DEV_ROOT,
            "--proc", "/proc", "--unshare-user"]
    for root in _protected_roots(att):
        argv += ["--ro-bind", root, root]
    for src, dst, read_only in write_set(att):
        argv += ["--ro-bind" if read_only else "--bind", src, dst]
    for path in existing(att.get("db_paths") or []):
        argv += ["--ro-bind", path, path]
    for path in _grant_paths(att):
        argv += ["--bind", path, path]
    tail = list(command) + [flag for flag in _fence_args(att) if flag not in command]
    return argv + ["--die-with-parent", "--"] + tail


def _darwin_scope(att: dict) -> tuple[list[str], list[str], list[str], list[str]]:
    """The ``(deny, allow)`` path lists ``fence_darwin.profile`` needs:
    protected roots plus the database to deny, carve-outs plus grants to
    allow back in.
    """
    cwd = att.get("cwd") or ""
    deny = _protected_roots(att) + existing(att.get("db_paths") or [])
    deny_git = git_fence.darwin_protected_git_paths(cwd)
    allow = darwin_write_set(att) + _grant_paths(att)
    allow_git = existing([git_fence._worktree_gitdir(cwd) or ""])
    return deny, allow, deny_git, allow_git


def launch_argv(adapter) -> list[str]:
    """Build a fenced spawn argv; adapters may replace incompatible CLI sandboxes."""
    command = adapter.build_command()
    from . import fence_probe

    result = fence_probe.cached_result()
    if result is not None and not result[0]:
        raise FenceUnavailable(_refusal(result[1], result[2]))
    if not features.enabled("write_fence"):
        return command
    available, reason = backend_available()
    if not available:
        raise FenceUnavailable(_refusal(reason))
    att = adapter.att
    if backend() == "sandbox-exec":
        deny, allow, deny_git, allow_git = _darwin_scope(att)
        return fence_darwin.argv(deny, allow, deny_git, allow_git,
                                 command, _fence_args(att))
    return _bwrap_argv(att, command)
