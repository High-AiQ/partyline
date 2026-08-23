"""Live presentation facts derived from an attachment's exact cwd."""

import asyncio
import os
import subprocess
from collections.abc import Mapping

from .attachment_contracts import AttachmentResponse, CwdGitState

GIT_TIMEOUT_SECONDS = 3


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


async def attachment_response(attachment: Mapping[str, object]) -> dict[str, object]:
    """Add live cwd identity at the HTTP/WebSocket presentation boundary."""
    payload = dict(attachment)
    payload["cwd_git"] = await asyncio.to_thread(
        cwd_git_state, str(attachment.get("cwd", ""))
    )
    return AttachmentResponse.model_validate(payload).model_dump()


def cwd_git_digest(cwd: str) -> str:
    """Format the live cwd identity for a wake digest, or nothing outside git."""
    state = cwd_git_state(cwd)
    if state is None:
        return ""
    cleanliness = "dirty" if state.dirty else "clean"
    return f"(cwd git: {state.sha} {cleanliness})"
