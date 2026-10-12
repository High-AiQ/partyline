"""Stop one runaway descendant of a process, by pid, without a pkill.

Finding 5.10: when a worker's build or test run eats its memory budget, the
only remedy partyline could give was prose — "stop what is growing" — and the
only tool the prose named was `pkill -f`, which matches command lines across
*every* attachment on the host and has taken out other lines' work. This
endpoint names one pid instead, and refuses anything that is not a strict
descendant of the attachment's own process.

The pid arrives in the namespace the caller lives in — a fenced process sees
its children under its own pids — while the server lives outside every
fence. The map is `/proc/<pid>/status`'s `NSpid`: its last field is the pid
the process itself would use, so a requested pid is matched against that
field across this attachment's descendants and resolved to the host pid
before any signal is sent.

Two callers: the attachment itself (its token, so a worker can stop its own
runaway child) and the line's captain (who is responsible for the line's
budget). The agent process is never a valid target: killing the pty is the
detach path's job, not a pid argument's — and in a namespace the agent's own
pid is its namespaced one, so the check is on that view, not the host pid.
"""

from __future__ import annotations

import os
import signal as signal_module
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .auth_guard import request_principal
from .top_processes import _descendants, namespace_pid

# Windows has no SIGKILL; os.kill(pid, SIGTERM) there is TerminateProcess —
# the one signal that always stops the process on every platform.
SIGNALS = {"TERM": signal_module.SIGTERM,
           "KILL": getattr(signal_module, "SIGKILL", signal_module.SIGTERM)}


class SignalIn(BaseModel):
    pid: int = Field(ge=1)
    signal: Literal["TERM", "KILL"] = "TERM"


def _snapshot():
    from .memory_sampler import process_snapshot

    return process_snapshot("linux")


def resolve_descendant(host_pid: int, requested_pid: int,
                       snapshot: tuple[dict[int, int], dict[int, int]] | None = None,
                       ) -> int | None:
    """The host pid of this process's descendant the caller sees as ``requested_pid``.

    The match is on the last `NSpid` field — the pid in the caller's own
    namespace — and only strict descendants qualify: the agent's own pid, in
    whatever namespace it is spoken about, is never resolvable.
    """
    if requested_pid <= 0 or requested_pid == namespace_pid(host_pid):
        return None
    if snapshot is None:
        snapshot = _snapshot()
    if snapshot is None:
        return None
    parents, _rss = snapshot
    members = {member for member in _descendants(parents, host_pid)
               if member != host_pid}
    for member in members:
        if namespace_pid(member) == requested_pid:
            return member
    return None


def signal_router(runtime) -> APIRouter:
    router = APIRouter()

    @router.post("/api/attachments/{att_id}/signal")
    async def signal_descendant(att_id: str, body: SignalIn, request: Request):
        principal = request_principal(request)
        target = runtime.db.get_attachment(att_id)
        if target is None:
            raise HTTPException(404)
        by_self = principal.kind == "machine" and principal.attachment_id == att_id
        by_captain = (principal.kind == "machine" and principal.is_lead
                      and principal.conv_id == target["conv_id"])
        if not (by_self or by_captain):
            raise HTTPException(
                403, "only this process or its line's captain may signal its descendants")
        adapter = runtime.live.get(att_id)
        host_pid = getattr(getattr(adapter, "proc", None), "pid", None)
        if not isinstance(host_pid, int):
            raise HTTPException(409, "this attachment has no live process to signal")
        host_target = resolve_descendant(host_pid, body.pid)
        if host_target is None:
            raise HTTPException(
                422, f"pid {body.pid} is not a descendant of this process "
                     "(pids are as the process sees them; the agent itself is never a target)")
        os.kill(host_target, SIGNALS[body.signal])
        return {"ok": True, "pid": body.pid, "signal": body.signal}

    return router
