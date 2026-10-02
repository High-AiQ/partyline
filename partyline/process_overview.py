"""Read-only overview of a line and its descendants' live processes.

A person reclaiming an idle tree should not have to shell into each line to
learn what is still running: one GET shows every line's goal state, its
accepted hand-off SHA, and each live process with its phase and best-effort
memory. This is the read side of the reclaim duty — the write side is the
existing detach and retire controls, and it stays put.
"""

from __future__ import annotations

import sys

from fastapi import FastAPI, Request

from .auth_guard import request_principal
from .hierarchy import descendants
from .machine_scope import deny_unless
from .presence import IDLE
from .process_overview_contracts import (
    ProcessOverviewAttachment,
    ProcessOverviewLine,
    ProcessOverviewResponse,
)

LIVE = ("starting", "running")


def read_rss_bytes(pid: int | None) -> int | None:
    """Best-effort resident memory from Linux ``/proc``; None when unknown.

    Degrades silently: a dead pid, a missing ``/proc`` entry, an unreadable
    status file, or a non-Linux host all answer None rather than failing the
    overview. Memory is a convenience here, never a reason to refuse a read.
    """
    if pid is None or not sys.platform.startswith("linux"):
        return None
    try:
        with open(f"/proc/{pid}/status", encoding="ascii", errors="replace") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _phase(runtime, att_id: str) -> str:
    presence = getattr(runtime, "presence", None)
    return presence.phase(att_id) if presence is not None else IDLE


def _attachment(runtime, att: dict) -> ProcessOverviewAttachment:
    adapter = runtime.live.get(att["id"])
    proc = getattr(adapter, "proc", None)
    pid = getattr(proc, "pid", None) if proc is not None else None
    measured = runtime.memory_usage.get(att["id"], {})
    return ProcessOverviewAttachment(
        id=att["id"],
        handle=att["name"],
        adapter=att["adapter"],
        pid=pid,
        phase=_phase(runtime, att["id"]),
        rss_bytes=read_rss_bytes(pid),
        memory_usage_bytes=measured.get("usage_bytes"),
        memory_cap_bytes=measured.get("cap_bytes"),
        memory_percent=measured.get("percent"),
        runtime_started_at=att.get("runtime_started_at"),
    )


def _line(runtime, conv_id: str) -> ProcessOverviewLine:
    conv = runtime.db.get_conversation(conv_id) or {}
    attachments = [
        _attachment(runtime, att)
        for att in runtime.db.list_attachments(conv_id)
        if att["status"] in LIVE and att["id"] in runtime.live
    ]
    return ProcessOverviewLine(
        id=conv.get("id", conv_id),
        name=conv.get("name", ""),
        goal_set=bool((conv.get("goal") or "").strip()),
        accepted_sha=conv.get("accepted_sha") or None,
        attachments=attachments,
    )


def process_overview(runtime, conv_id: str) -> ProcessOverviewResponse:
    return ProcessOverviewResponse(
        lines=[
            _line(runtime, line_id)
            for line_id in [conv_id, *descendants(runtime.db, conv_id)]
        ]
    )


def register_process_overview_route(app: FastAPI, runtime) -> None:
    @app.get(
        "/api/conversations/{conv_id}/process-overview",
        response_model=ProcessOverviewResponse,
    )
    async def get_process_overview(request: Request, conv_id: str):
        deny_unless(runtime.db, request_principal(request), conv_id, "read")
        return process_overview(runtime, conv_id)
