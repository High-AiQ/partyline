"""Inspect failures and set the next activation's finite memory budget."""

import os

from fastapi import HTTPException, Request

from .auth_guard import request_principal
from .machine_scope import deny_unless_attachment
from .memory_contracts import MemoryLimitRequest, MemorySettings
from .process_incidents import last_incident
from .process_memory import parse_size, process_memory_limit
from .server_memory import host_memory_bytes
from .system_notice import post_system_notice


def maximum_bytes():
    configured = process_memory_limit({"PARTYLINE_PROCESS_MEMORY_LIMIT": os.environ.get(
        "PARTYLINE_MAX_PROCESS_MEMORY_LIMIT", "8G")})
    return min(parse_size(configured), host_memory_bytes() * 3 // 4)


def memory_settings(db, att):
    return MemorySettings(
        configured_limit=att.get("memory_limit"),
        effective_limit=att.get("memory_limit") or process_memory_limit(),
        maximum_bytes=maximum_bytes(), last_incident=last_incident(db, att["id"]),
    )


def register_memory_routes(app, runtime):
    @app.get("/api/attachments/{att_id}/memory", response_model=MemorySettings)
    async def get_memory(request: Request, att_id: str):
        deny_unless_attachment(runtime.db, request_principal(request), att_id, "read")
        return memory_settings(runtime.db, runtime.db.get_attachment(att_id))

    @app.put("/api/attachments/{att_id}/memory", response_model=MemorySettings)
    async def set_memory(request: Request, att_id: str, body: MemoryLimitRequest):
        actor = request_principal(request)
        deny_unless_attachment(runtime.db, actor, att_id, "attach")
        if actor.kind == "machine" and actor.attachment_id == att_id:
            raise HTTPException(403, "a process cannot grant itself a memory budget")
        if body.limit is not None and parse_size(body.limit) > maximum_bytes():
            raise HTTPException(400, f"memory limit exceeds the host ceiling of {maximum_bytes()} bytes")
        async with runtime.db._runtime_serialized_async():
            att = runtime.db.get_attachment(att_id)
            if att is None:
                raise HTTPException(404, "attachment was removed")
            if att_id in runtime.live or att["status"] not in ("exited", "detached"):
                raise HTTPException(409, "stop the attachment before changing its memory limit")
            runtime.db._exec("UPDATE attachments SET memory_limit=? WHERE id=?", (body.limit, att_id))
        await post_system_notice(runtime, att["conv_id"],
                                 f"Memory limit for {att['name']} set to {body.limit or 'the host default'} "
                                 "for its next activation.", actor=actor)
        return memory_settings(runtime.db, runtime.db.get_attachment(att_id))
