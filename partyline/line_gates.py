"""A line's declared gates, run fenced at the SHA when accept is asked to.

Finding 5.6: captains already reuse workers' gate evidence more than they
should. With gates declared (`PUT …/gates`), `accept {"run_gates": true}`
makes a scratch checkout at the SHA and runs each command in it, in order,
stopping at the first failure — never on the captain's word alone.

Security is the crux: the server must not run a captain's commands
unsandboxed. Every command runs through the same write fence the line's
processes get (`fence.command_argv`), under the same memory scope, in the
scratch checkout as the working directory. Where no fence exists the request
answers 501 rather than running unfenced.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import time

from fastapi import HTTPException, Request

from . import fence
from .auth_guard import request_principal
from .machine_scope import deny_unless, is_human
from .process_memory import backstop_limit, process_memory_limit, scope_argv
from .resource_budget import host_resources, settings
from .scratch_worktrees import create_scratch_worktree, remove_scratch_path

MAX_COMMANDS = 10
MAX_COMMAND_CHARS = 500
MAX_TIMEOUT_S = 4 * 3600
TAIL_LINES = 40


def set_gates(db, conv_id: str, commands: list[str], timeout_s: int) -> dict:
    commands = clean_commands(commands)
    db._exec(
        "INSERT INTO line_gates(conv_id,commands,timeout_s,updated_at) "
        "VALUES(?,?,?,?) ON CONFLICT(conv_id) DO UPDATE SET "
        "commands=excluded.commands, timeout_s=excluded.timeout_s, "
        "updated_at=excluded.updated_at",
        (conv_id, json.dumps(commands), int(timeout_s), time.time()),
    )
    return get_gates(db, conv_id)


def get_gates(db, conv_id: str) -> dict | None:
    row = db._exec(
        "SELECT commands, timeout_s FROM line_gates WHERE conv_id=?",
        (conv_id,)).fetchone()
    if row is None:
        return None
    return {"commands": json.loads(row["commands"]), "timeout_s": row["timeout_s"]}


def clean_commands(commands) -> list[str]:
    if not isinstance(commands, list) or not commands:
        raise ValueError("commands must be a non-empty list of strings")
    if len(commands) > MAX_COMMANDS:
        raise ValueError(f"at most {MAX_COMMANDS} commands")
    cleaned = []
    for command in commands:
        if not isinstance(command, str) or not command.strip():
            raise ValueError("commands must be non-empty strings")
        if len(command) > MAX_COMMAND_CHARS:
            raise ValueError(f"command longer than {MAX_COMMAND_CHARS} characters")
        cleaned.append(command.strip())
    return cleaned


def _tail(text: str, lines: int = TAIL_LINES) -> str:
    combined = "\n".join(part for part in (text or "").splitlines() if part.strip())
    kept = combined.splitlines() or [""]
    return "\n".join(kept[-lines:])


def _gate_attachment(db, conv_id: str, scratch_path: str, scratch_sha: str) -> dict:
    """An attachment-shaped view of the scratch checkout for the fence.

    The fence binds exactly what a line process would get — the scratch tree
    as the working directory, its git metadata, the line's write grants and
    the protected database — nothing more.
    """
    from .fence_protect import database_paths
    from .scratch_worktrees import list_scratch_worktrees

    return {
        "id": f"{conv_id}-gates",
        "conv_id": conv_id,
        "cwd": scratch_path,
        "adapter_metadata": {},
        "write_grants": [dict(r) for r in db._exec(
            "SELECT * FROM conversation_write_grants WHERE conv_id=?",
            (conv_id,)).fetchall()],
        "scratch_worktrees": [
            row for row in list_scratch_worktrees(db, conv_id)
            if row["sha"] == scratch_sha],
        "db_paths": database_paths(db),
    }


async def run_line_gates(runtime, conv_id: str, sha: str, spec: dict) -> list[dict]:
    """Run the declared commands in a fenced scratch checkout at the SHA.

    Every command goes through the write fence and the memory scope, off the
    event loop, with the declared timeout; the run stops at the first
    failure. The scratch checkout is removed afterwards either way.
    """
    if not (fence.features.enabled("write_fence") and fence.backend_available()[0]):
        raise HTTPException(501, "no write fence on this host; gates would run unfenced")
    created = create_scratch_worktree(runtime.db, conv_id, sha)
    scratch_path = created["path"]
    scratch_sha = created["sha"]
    att = _gate_attachment(runtime.db, conv_id, scratch_path, scratch_sha)
    config = settings(runtime.db)
    memory_limit = process_memory_limit(
        {"PARTYLINE_PROCESS_MEMORY_LIMIT": f"{config['default_process_memory_bytes'] // 2**20}M"})
    hard = backstop_limit(memory_limit, host_resources().ram_bytes)
    results: list[dict] = []
    try:
        for command in spec["commands"]:
            try:
                argv = fence.command_argv(att, ["sh", "-c", command])
                scoped = scope_argv(argv, hard)
            except fence.FenceUnavailable as exc:
                raise HTTPException(501, str(exc)) from exc
            try:
                done = await asyncio.to_thread(
                    subprocess.run, scoped, cwd=scratch_path,
                    capture_output=True, text=True, timeout=spec["timeout_s"])
                exit_code: int | str = done.returncode
                tail = _tail(done.stdout + "\n" + done.stderr)
            except subprocess.TimeoutExpired as expired:
                exit_code = "timeout"
                tail = _tail((expired.stdout or "") + "\n" + (expired.stderr or ""))
            results.append({"command": command, "exit": exit_code, "tail": tail})
            if exit_code != 0:
                break
    finally:
        remove_scratch_path(scratch_path)
        runtime.db._exec("DELETE FROM scratch_worktrees WHERE conv_id=? AND sha=?",
                         (conv_id, scratch_sha))
    return results


def register_gates_routes(app, runtime) -> None:
    @app.put("/api/conversations/{conv_id}/gates")
    async def put_gates(request: Request, conv_id: str, body: dict):
        db = runtime.db
        principal = request_principal(request)
        if not is_human(principal):
            deny_unless(db, principal, conv_id, "assign")
        try:
            commands = clean_commands(body.get("commands"))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        timeout_s = body.get("timeout_s", 1800)
        if not isinstance(timeout_s, int) or not 1 <= timeout_s <= MAX_TIMEOUT_S:
            raise HTTPException(422, "timeout_s must be between 1 and 14400 seconds")
        return set_gates(db, conv_id, commands, timeout_s)

    @app.get("/api/conversations/{conv_id}/gates")
    async def get_gates_route(request: Request, conv_id: str):
        db = runtime.db
        deny_unless(db, request_principal(request), conv_id, "read")
        gates = get_gates(db, conv_id)
        if gates is None:
            raise HTTPException(404, "no gates declared on this line")
        return gates
