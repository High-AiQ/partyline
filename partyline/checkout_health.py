"""Is the checkout a line works in current, and is it clean?

A root captain briefed itself from a checkout whose ``main`` was 102 commits
behind ``origin/main`` and carried an old, uncommitted plan document. Nothing
told it, so it planned the wrong book; every child line it spawned was cut
from the same stale base. Git knows all of this in one fetch and three
counts, so the line hears it when a captain is appointed and when a child is
born, and a machine may not cut a child from a base that is behind its
upstream: work started there is merged into the past.

The check never changes the checkout. Pulling, resetting or stashing a
person's working tree is theirs to do; the report says what it found and the
captain asks.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

FETCH_TIMEOUT = 20
GIT_TIMEOUT = 5


def _git(cwd: str, *args: str, timeout: int = GIT_TIMEOUT) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, encoding="utf-8",
                          errors="replace", env=env, timeout=timeout, check=False)


@dataclass(frozen=True)
class CheckoutHealth:
    sha: str
    branch: str            # "HEAD" when detached
    upstream: str | None   # e.g. origin/main; None when the branch tracks nothing
    fetched: bool          # the upstream was refreshed just now
    ahead: int
    behind: int
    modified: int          # tracked files with changes
    untracked: int

    @property
    def stale(self) -> bool:
        return self.behind > 0

    @property
    def dirty(self) -> bool:
        return bool(self.modified or self.untracked)


def _count(cwd: str, spec: str) -> int:
    done = _git(cwd, "rev-list", "--count", spec)
    return int(done.stdout.strip() or 0) if done.returncode == 0 else 0


def inspect(path: str | None, *, fetch: bool = True) -> CheckoutHealth | None:
    """Read the checkout's state; refresh its upstream first when asked.

    A failed fetch (offline, no credentials) is not an error: the report says
    the upstream was not refreshed and the counts are against what was last
    fetched. Outside a repository there is nothing to report."""
    if not path or not os.path.isdir(path):
        return None
    try:
        head = _git(path, "rev-parse", "--short=7", "HEAD")
        if head.returncode or not head.stdout.strip():
            return None
        branch = _git(path, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "HEAD"
        upstream_done = _git(path, "rev-parse", "--abbrev-ref", "@{upstream}")
        upstream = upstream_done.stdout.strip() if upstream_done.returncode == 0 else None
        fetched = False
        if fetch and upstream:
            remote = upstream.split("/", 1)[0]
            fetched = _git(path, "fetch", "--quiet", remote, timeout=FETCH_TIMEOUT).returncode == 0
        ahead = _count(path, "@{upstream}..HEAD") if upstream else 0
        behind = _count(path, "HEAD..@{upstream}") if upstream else 0
        status = _git(path, "status", "--porcelain", "--untracked-files=normal")
        lines = [line for line in status.stdout.splitlines() if line.strip()]
        untracked = sum(1 for line in lines if line.startswith("??"))
        return CheckoutHealth(
            sha=head.stdout.strip(), branch=branch, upstream=upstream, fetched=fetched,
            ahead=ahead, behind=behind, modified=len(lines) - untracked, untracked=untracked,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def describe(health: CheckoutHealth | None) -> str | None:
    """One line for the room; None outside git."""
    if health is None:
        return None
    where = f"{health.sha} on {health.branch}"
    if health.upstream is None:
        sync = "tracking no upstream"
    elif not health.ahead and not health.behind:
        sync = f"up to date with {health.upstream}"
    else:
        parts = []
        if health.behind:
            parts.append(f"{_plural(health.behind, 'commit')} behind")
        if health.ahead:
            parts.append(f"{_plural(health.ahead, 'local commit')} ahead of")
        sync = f"{' and '.join(parts)} {health.upstream}"
    if health.upstream and not health.fetched:
        sync += " (upstream not refreshed)"
    tree = "clean"
    if health.dirty:
        bits = []
        if health.modified:
            bits.append(f"{_plural(health.modified, 'modified file')}")
        if health.untracked:
            bits.append(f"{_plural(health.untracked, 'untracked file')}")
        tree = ", ".join(bits)
    text = f"☏ checkout: {where}, {sync}; working tree {tree}"
    if health.stale:
        text += (" — STALE: work planned from here starts in the past. Nobody but a person "
                 "pulls, resets or stashes this checkout; ask before basing anything on it")
    elif health.dirty:
        text += " — uncommitted work belongs to someone; do not stage, stash or discard it"
    return text


def stale_base_reason(health: CheckoutHealth | None) -> str | None:
    """Why a machine may not cut a child line from this checkout, or None."""
    if health is None or not health.stale:
        return None
    return (f"this checkout is {_plural(health.behind, 'commit')} behind {health.upstream}; a "
            "child line cut from it would start in the past — ask the person to bring "
            f"{health.branch} up to date, or create the child with base:\"upstream\"")


def default_upstream(path: str | None) -> str | None:
    """The repository's configured upstream default: ``origin/HEAD`` when the
    clone sets it, else the current branch's upstream. None when the checkout
    has neither — there is nothing fetched to cut from."""
    if not path or not os.path.isdir(path):
        return None
    head = _git(path, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if head.returncode == 0 and head.stdout.strip():
        return head.stdout.strip()
    tracked = _git(path, "rev-parse", "--abbrev-ref", "@{upstream}")
    if tracked.returncode == 0 and tracked.stdout.strip():
        return tracked.stdout.strip()
    return None


def child_base_ref(
    path: str | None, want_upstream: bool, human: bool, health: CheckoutHealth | None,
) -> tuple[str | None, str | None]:
    """Where a new child line branches from, and why it may not.

    ``(None, None)`` is today's default: the parent checkout's HEAD. With
    ``want_upstream`` — the deliberate cut for a checkout left behind — the
    default upstream is fetched and returned as the start point instead, so
    the stale-checkout refusal does not apply: the child starts at what the
    upstream already has, never in the past.
    """
    if not want_upstream:
        if not human and (reason := stale_base_reason(health)):
            return None, reason
        return None, None
    ref = default_upstream(path)
    if ref is None:
        return None, ("no upstream to cut from: the repository has neither an origin/HEAD "
                      "nor an upstream on its current branch")
    remote = ref.split("/", 1)[0]
    fetched = _git(path, "fetch", "--quiet", remote, timeout=FETCH_TIMEOUT)
    if fetched.returncode != 0:
        return None, f"the upstream {ref} could not be fetched from {remote}"
    return ref, None
