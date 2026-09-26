"""Cursor startup selection and failure diagnostics."""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import signal
import sys
from pathlib import Path


OUTPUT_LIMIT = 600
TERMINATE_GRACE = 0.5
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]+")
_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)?)?")
_SECRET = re.compile(
    r"(?i)(authorization\s*:\s*bearer\s+|bearer\s+|"
    r"(?:api[_ -]?key|authorization|password|secret|token)\s*[:=]\s*)\S+"
)
_SECRET_FLAGS = {"--api-key", "--header"}


def is_git_worktree(cwd: str) -> bool:
    """Whether ``cwd`` is a linked Git worktree rather than a repository root."""
    return Path(cwd, ".git").is_file()


def workspace_command(cmd: list[str], cwd: str, resume: bool) -> list[str]:
    """Select a linked worktree explicitly for Cursor's fresh-session CLI."""
    explicit = any(arg == "--workspace" or arg.startswith("--workspace=") for arg in cmd)
    if not resume and is_git_worktree(cwd) and not explicit:
        return [*cmd, "--workspace", cwd]
    return cmd


def cursor_command(cmd: list[str], cwd: str, resume: bool, session_id: str) -> list[str]:
    """Build Cursor's actual argv for a fresh or resumed attachment."""
    command = workspace_command(cmd or ["agent", "--yolo", "--trust"], cwd, resume)
    if resume and session_id and "--resume" not in command and "-r" not in command:
        return [*command, "--resume", session_id]
    return command


def startup_diagnostics(argv: list[str], cwd: str, terminal: str) -> str:
    """Return bounded, secret-redacted facts for an unclaimed Cursor startup."""
    workspace = _workspace(argv) or cwd
    trust = Path.home() / ".cursor" / "projects" / _slug(workspace) / ".workspace-trusted"
    return (
        "Cursor startup diagnostics: "
        f"argv={shlex.join(_redacted_argv(argv))}; cwd={cwd!r}; "
        f"linked_worktree={is_git_worktree(cwd)}; workspace={workspace!r}; "
        f"trust_record={str(trust)!r}; trust_record_present={trust.is_file()}; "
        f"initial_cursor_output={_clean(terminal)!r}"
    )


async def terminate_process(proc, grace: float = TERMINATE_GRACE) -> None:
    """End a failed startup without marking the attachment deliberately detached."""
    if proc is None or proc.poll() is not None:
        return
    if sys.platform == "win32":
        await proc.close()
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    await asyncio.sleep(grace)
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def _workspace(argv: list[str]) -> str | None:
    for index, arg in enumerate(argv):
        if arg == "--workspace" and index + 1 < len(argv):
            return argv[index + 1]
        if arg.startswith("--workspace="):
            return arg.split("=", 1)[1]
    return None


def _redacted_argv(argv: list[str]) -> list[str]:
    result: list[str] = []
    redact_next = False
    for arg in argv:
        if redact_next:
            result.append("[REDACTED]")
            redact_next = False
        elif arg in _SECRET_FLAGS:
            result.append(arg)
            redact_next = True
        elif any(arg.startswith(f"{flag}=") for flag in _SECRET_FLAGS):
            result.append(f"{arg.split('=', 1)[0]}=[REDACTED]")
        else:
            result.append(_SECRET.sub(r"\1[REDACTED]", arg))
    return result


def _clean(terminal: str) -> str:
    text = _SECRET.sub(r"\1[REDACTED]", _CONTROL.sub(" ", _ANSI.sub("", terminal)))
    return " ".join(text.split())[:OUTPUT_LIMIT]


def _slug(cwd: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", cwd).strip("-")
