"""REST routes for attach presets. Split from `server.py` for its line cap."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from .contracts import OkResponse, PresetIn, PresetResponse
from .runtime import NAME_RE, RESERVED_NAMES


def presets_router(runtime, adapters) -> APIRouter:
    router = APIRouter()

    @router.get("/api/presets", response_model=list[PresetResponse])
    async def presets():
        return runtime.db.list_presets()

    @router.post("/api/presets", response_model=PresetResponse)
    async def create_preset(body: PresetIn):
        return _save_preset(str(uuid.uuid4()), body)

    @router.put("/api/presets/{preset_id}", response_model=PresetResponse)
    async def update_preset(preset_id: str, body: PresetIn):
        if not runtime.db.get_preset(preset_id):
            raise HTTPException(404)
        return _save_preset(preset_id, body)

    @router.delete("/api/presets/{preset_id}", response_model=OkResponse)
    async def delete_preset(preset_id: str):
        runtime.db.delete_preset(preset_id)
        return {"ok": True}

    def _save_preset(preset_id: str, body: PresetIn):
        if not body.title.strip():
            raise HTTPException(400, "preset needs a title")
        if not NAME_RE.match(body.name):
            raise HTTPException(400, "name must be alphanumeric ([A-Za-z0-9_.-], max 32)")
        if body.name.lower() in RESERVED_NAMES:
            raise HTTPException(400, f"'{body.name}' is a reserved handle")
        if body.adapter not in adapters:
            raise HTTPException(400, f"adapter must be one of {sorted(adapters)}")
        return runtime.db.save_preset(
            preset_id, body.title.strip(), body.name, body.adapter, body.command.strip())

    return router
