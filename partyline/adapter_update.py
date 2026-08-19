"""Run an adapter's optional host-level update command before spawn.

This mutates the machine's CLI, not the pty child. Tests inject `runner` so
the suite never invokes a vendor executable.
"""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass

TIMEOUT_SECONDS = 120
OUTPUT_CAP = 8000

_lock = asyncio.Lock()


@dataclass(frozen=True)
class UpdateResult:
    exit_code: int
    output: str


def normalize_update_command(value: object) -> list[str] | None:
    """Empty or omitted is none; anything else must be a non-empty argv."""
    if value is None or value == []:
        return None
    if not isinstance(value, list) or not value:
        raise ValueError("update_command must be an argv array")
    if not all(isinstance(item, str) and item for item in value):
        raise ValueError("update_command must be an argv array of non-empty strings")
    return list(value)


def update_argv(metadata: Mapping[str, Mapping[str, object]], adapter_id: str) -> list[str] | None:
    row = metadata.get(adapter_id) or {}
    return normalize_update_command(row.get("update_command"))


def requested_update_argv(
    metadata: Mapping[str, Mapping[str, object]], adapter_id: str, requested: bool
) -> list[str] | None:
    """None when the box is unchecked; ValueError when checked with no command."""
    if not requested:
        return None
    argv = update_argv(metadata, adapter_id)
    if argv is None:
        raise ValueError(f"the {adapter_id} adapter has no update command")
    return argv


def format_notice(handle: str, argv: Sequence[str], result: UpdateResult) -> str:
    quoted = " ".join(argv)
    body = result.output.strip() or "(no output)"
    extra = len(body) - OUTPUT_CAP
    if extra > 0:
        body = body[:OUTPUT_CAP] + f"\n… [truncated, {extra} more chars]"
    return f"↑ @{handle} update · `{quoted}` · exit {result.exit_code}\n{body}"


def default_runner(argv: Sequence[str], timeout: float = TIMEOUT_SECONDS) -> UpdateResult:
    """Host-global updater: scratch cwd so a project tree is not the working dir."""
    try:
        with tempfile.TemporaryDirectory() as cwd:
            completed = subprocess.run(
                list(argv), capture_output=True, text=True, timeout=timeout,
                cwd=cwd, check=False,
            )
    except subprocess.TimeoutExpired as exc:
        out = f"{exc.stdout or ''}{exc.stderr or ''}".strip()
        detail = "update timed out"
        return UpdateResult(124, f"{out}\n{detail}".strip() if out else detail)
    except OSError as exc:
        return UpdateResult(127, str(exc))
    return UpdateResult(completed.returncode, f"{completed.stdout or ''}{completed.stderr or ''}")


Runner = Callable[[Sequence[str]], UpdateResult]
Poster = Callable[[str, str, str, str], Awaitable[object]]


async def apply_update(
    post_message: Poster,
    conv_id: str,
    handle: str,
    argv: Sequence[str],
    *,
    runner: Runner = default_runner,
) -> UpdateResult:
    """Serialize host updates, then always post the captured output."""
    async with _lock:
        result = await asyncio.to_thread(runner, list(argv))
    await post_message(conv_id, "system", "system", format_notice(handle, argv, result))
    return result
