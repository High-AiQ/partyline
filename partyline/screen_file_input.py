"""Authorize a short-lived helper download for an element file input action."""
import json
import secrets
from contextlib import contextmanager

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from .auth_guard import bearer_token
from .media_files import MAX_FILE_BYTES
from .media_routes import deny_unless_media_read, handed_to
from .screen_audit import record
from .screen_grants import require_window

MAX_TOTAL = 200 * 1024 * 1024


def resolve_files(hub, principal, ids):
    files, total = [], 0
    for ident in ids:
        row = hub.runtime.db._exec("SELECT conv_id FROM images WHERE id=?", (ident,)).fetchone()
        located = hub.media_store.file_for(ident, "original") if row else None
        if not row or not located:
            raise HTTPException(404, "unknown or unreadable media")
        try:
            if not handed_to(hub.runtime.db, principal, ident):
                deny_unless_media_read(hub.runtime.db, principal, row["conv_id"])
        except HTTPException as exc:
            raise HTTPException(404, "unknown or unreadable media") from exc
        path, mime, name = located
        length = path.stat().st_size
        if length > MAX_FILE_BYTES:
            raise HTTPException(413, "file exceeds the media per-file limit")
        total += length
        if total > MAX_TOTAL:
            raise HTTPException(413, "files exceed the 200 MiB per-call limit")
        files.append({"id": ident, "path": path, "name": name or path.name, "bytes": length, "mime": mime})
    return files, total


@contextmanager
def ticket(hub, principal, grant, files, path_count=0):
    if not hasattr(hub, "file_tickets"):
        hub.file_tickets = {}
    key = secrets.token_urlsafe(32)
    hub.file_tickets[key] = (principal, grant, files, path_count)
    try:
        yield key
    finally:
        hub.file_tickets.pop(key, None)


def audit_files(hub, principal, grant, ids, total, *, include_ids=True):
    info = {"grant": grant["id"], "line": principal.conv_id, "process": principal.name,
            "operation": "set_files", "file_count": len(ids), "total_bytes": total}
    if include_ids:
        info["media_ids"] = ids
    record(hub.runtime.db, grant["id"], principal.conv_id or grant["conv_id"], principal.name,
           json.dumps(info, separators=(",", ":")))


class LocalFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=32767)
    bytes: int = Field(ge=0, le=MAX_FILE_BYTES)


class LocalAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paths: list[LocalFile] = Field(min_length=1, max_length=10)


def router_for(hub):
    router = APIRouter()

    @router.get("/api/screen/file-input/{key}/{index}")
    async def download(key: str, index: int, request: Request):
        item = getattr(hub, "file_tickets", {}).get(key)
        if not item:
            raise HTTPException(404)
        principal, grant, files, _ = item
        token = bearer_token(request.headers, request.query_params)
        row = hub.runtime.db._exec("SELECT id FROM screen_devices WHERE token_hash=? AND revoked_at IS NULL",
                                   (hub.digest(token),)).fetchone()
        if not row or row["id"] != grant["device_id"] or not 0 <= index < len(files):
            raise HTTPException(404)
        require_window(hub, principal, grant["id"])
        file = files[index]
        return FileResponse(file["path"], media_type=file["mime"], filename=file["name"])

    @router.post("/api/screen/file-input/{key}/audit")
    async def audit_local(key: str, body: LocalAudit, request: Request):
        item = getattr(hub, "file_tickets", {}).get(key)
        if not item:
            raise HTTPException(404)
        principal, grant, files, path_count = item
        token = bearer_token(request.headers, request.query_params)
        device = hub.runtime.db._exec(
            "SELECT id FROM screen_devices WHERE token_hash=? AND revoked_at IS NULL",
            (hub.digest(token),)).fetchone()
        if not device or device["id"] != grant["device_id"] or len(body.paths) != path_count:
            raise HTTPException(404)
        require_window(hub, principal, grant["id"])
        total = sum(f["bytes"] for f in files) + sum(f.bytes for f in body.paths)
        if total > MAX_TOTAL:
            raise HTTPException(413, "files exceed the 200 MiB per-call limit")
        info = {"grant": grant["id"], "line": principal.conv_id, "process": principal.name,
                "operation": "set_files", "file_count": len(files) + path_count,
                "total_bytes": total, "media_ids": [f["id"] for f in files],
                "paths": [f.model_dump() for f in body.paths]}
        record(hub.runtime.db, grant["id"], principal.conv_id or grant["conv_id"], principal.name,
               json.dumps(info, separators=(",", ":")))
        return {"ok": True}

    return router
