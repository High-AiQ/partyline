"""Live presentation facts derived from an attachment's exact cwd."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
import subprocess
from collections.abc import Mapping

from .attachment_contracts import AttachmentResponse, CwdGitState

GIT_TIMEOUT_SECONDS = 3
GIT_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="partyline-git")
GIT_LOOKUP_TIMEOUT_SECONDS = 0.75
GIT_LOOKUPS = {}


def _git(cwd: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    return subprocess.run(
        ["git", "-C", cwd, *args],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=GIT_TIMEOUT_SECONDS,
        check=False,
    )


def cwd_git_state(cwd: str) -> CwdGitState | None:
    """Read the current short commit and whole-worktree dirty state, if any."""
    try:
        revision = _git(cwd, "rev-parse", "--short=7", "HEAD")
    except (OSError, subprocess.TimeoutExpired):
        return None
    sha = revision.stdout.strip()
    if revision.returncode or not sha:
        return None
    try:
        status = _git(cwd, "status", "--porcelain", "--untracked-files=normal")
    except (OSError, subprocess.TimeoutExpired):
        return None
    if status.returncode:
        return None
    return CwdGitState(sha=sha, dirty=bool(status.stdout))


async def attachment_response(
    attachment: Mapping[str, object],
) -> dict[str, object]:
    """Add live cwd identity at the HTTP/WebSocket presentation boundary."""
    payload = dict(attachment)
    loop = asyncio.get_running_loop()
    cwd = str(attachment.get("cwd", ""))
    key = (loop, cwd)
    lookup = GIT_LOOKUPS.get(key)
    if lookup is None:
        lookup = loop.run_in_executor(GIT_EXECUTOR, cwd_git_state, cwd)
        GIT_LOOKUPS[key] = lookup

        def forget(completed):
            if GIT_LOOKUPS.get(key) is completed:
                del GIT_LOOKUPS[key]

        lookup.add_done_callback(forget)
    try:
        payload["cwd_git"] = await asyncio.wait_for(
            asyncio.shield(lookup),
            GIT_LOOKUP_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        payload["cwd_git"] = None
    return AttachmentResponse.model_validate(payload).model_dump()


def attach_memory_usage(
    payload: dict[str, object], memory_usage: Mapping[str, object] | None,
) -> dict[str, object]:
    """Attach the latest advisory sample without changing the response builder API."""
    if memory_usage:
        payload.update({
            "memory_usage_bytes": memory_usage.get("usage_bytes"),
            "memory_cap_bytes": memory_usage.get("cap_bytes"),
            "memory_percent": memory_usage.get("percent"),
        })
    return payload


def cwd_git_digest(cwd: str) -> str:
    """Format the live cwd identity for a wake digest, or nothing outside git."""
    state = cwd_git_state(cwd)
    if state is None:
        return ""
    cleanliness = "dirty" if state.dirty else "clean"
    behind = _behind_upstream(cwd)
    stale = f", {behind} behind upstream" if behind else ""
    return f"(cwd git: {state.sha} {cleanliness}{stale})"


def _behind_upstream(cwd: str) -> int:
    """Commits on the tracked upstream (as last fetched) missing from HEAD."""
    try:
        done = _git(cwd, "rev-list", "--count", "HEAD..@{upstream}")
    except (OSError, subprocess.TimeoutExpired):
        return 0
    return int(done.stdout.strip() or 0) if not done.returncode else 0
