"""Settings routes for speech presets: list, edit, order, default, test. People only.

Every change rebuilds the shared registry (no restart) and broadcasts
``asr_presets_changed`` with a fresh snapshot for open browsers. Keys are
never accepted, stored, returned or logged: a preset names its variable and
the listing says only whether that variable is set.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ValidationError

from . import asr_presets, asr_store
from .asr_contracts import (
    AsrDefaultIn, AsrFields, AsrOrderIn, AsrPresetCreate, AsrPresetIn, AsrPresetsChangedEvent, AsrSettings,
    AsrTestResult,
)
from .auth_guard import request_principal
from .transcribe_routes import bounded_body
from .transcript import TakeFailed, TranscriberUnavailable


def _require_human(request: Request) -> None:
    if request_principal(request).kind != "user":
        raise HTTPException(403, "only people can change instance settings")


async def _parse(request: Request, model: type[BaseModel]):
    """Validate a body without FastAPI's default 422, which echoes the input: a pasted key must not bounce."""
    try:
        return model.model_validate(await request.json())
    except ValueError as exc:  # ValidationError is a ValueError; so is malformed JSON
        problems = exc.errors(include_input=False) if isinstance(exc, ValidationError) else []
        detail = "; ".join(f"{'.'.join(str(part) for part in p['loc'])}: {p['msg']}" for p in problems)
        raise HTTPException(422, detail or "the body must be JSON") from None


def _view(registry: asr_presets.AsrRegistry, name: str) -> dict:
    backend = registry.entries[name]
    meta = registry.meta.get(name) or asr_presets.PresetMeta("config", {"kind": backend.kind})
    fields = {key: value for key, value in meta.spec.items() if key != "kind"}
    key_env = fields.get("api_key_env")
    return {
        "name": name, "kind": backend.kind, "source": meta.source, "editable": meta.source == "database",
        "overrides_config": meta.overrides_config, "is_default": name == registry.default,
        "can_be_default": meta.source == "database" or name == registry.config_default,
        **backend.status(), "fields": AsrFields(**fields),
        "key_env": key_env, "key_set": bool(os.environ.get(key_env)) if key_env else None,
    }


def listing(db) -> dict:
    registry = asr_presets.shared_registry(db)
    return {"default": registry.default, "presets": [_view(registry, name) for name in registry.entries]}


def asr_settings_router(runtime, clock: Callable[[], float] = time.perf_counter) -> APIRouter:
    router = APIRouter()
    base = "/api/settings/asr"

    async def changed() -> dict:
        asr_presets.rebuild(runtime.db)
        settings = listing(runtime.db)
        await runtime.broadcast_all(AsrPresetsChangedEvent(settings=settings))
        return settings

    def spec_for(name: str, body: AsrPresetIn) -> dict:
        try:
            return asr_presets.validate(name, body.kind, body.fields.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(422, str(exc).removeprefix(f"[[asr]] {name!r}: ")) from exc

    def stored(name: str) -> dict:
        row = asr_store.get_preset(runtime.db, name)
        if row is None:
            raise HTTPException(404, f"no editable speech preset named {name!r}")
        return row

    @router.get(base, response_model=AsrSettings)
    def get_settings(request: Request):
        _require_human(request)
        return listing(runtime.db)

    @router.post(f"{base}/presets", response_model=AsrSettings, status_code=201)
    async def create(request: Request):
        _require_human(request)
        body = await _parse(request, AsrPresetCreate)
        if asr_store.get_preset(runtime.db, body.name) is not None:
            raise HTTPException(409, f"a speech preset named {body.name!r} already exists")
        asr_store.save_preset(runtime.db, body.name, spec_for(body.name, body), create=True)
        return await changed()

    @router.put(f"{base}/presets/{{name}}", response_model=AsrSettings)
    async def update(request: Request, name: str):
        _require_human(request)
        body = await _parse(request, AsrPresetIn)
        stored(name)
        asr_store.save_preset(runtime.db, name, spec_for(name, body), create=False)
        return await changed()

    @router.delete(f"{base}/presets/{{name}}", response_model=AsrSettings)
    async def delete(request: Request, name: str):
        _require_human(request)
        stored(name)
        asr_store.delete_preset(runtime.db, name)
        return await changed()

    @router.put(f"{base}/default", response_model=AsrSettings)
    async def make_default(request: Request, body: AsrDefaultIn):
        _require_human(request)
        registry = asr_presets.shared_registry(runtime.db)
        if asr_store.get_preset(runtime.db, body.name) is not None:
            asr_store.set_default(runtime.db, body.name)
        elif body.name == registry.config_default:
            asr_store.set_default(runtime.db, None)
        elif body.name in registry.entries:
            raise HTTPException(409, "a config-file preset becomes the default by being first in the file; "
                                     "customize it here to make it the default")
        else:
            raise HTTPException(404, f"no speech preset named {body.name!r}")
        return await changed()

    @router.put(f"{base}/order", response_model=AsrSettings)
    async def order(request: Request, body: AsrOrderIn):
        _require_human(request)
        names = [row["name"] for row in asr_store.list_presets(runtime.db)]
        if sorted(body.names) != sorted(names):
            raise HTTPException(422, "order must list every settings preset exactly once")
        asr_store.reorder(runtime.db, body.names)
        return await changed()

    @router.post(f"{base}/presets/{{name}}/test", response_model=AsrTestResult)
    async def test(request: Request, name: str):
        _require_human(request)
        registry = asr_presets.shared_registry(runtime.db)
        if name not in registry.entries:
            raise HTTPException(404, f"no speech preset named {name!r}")
        backend = registry.entries[name]
        state = backend.status()
        if not state["available"]:
            raise HTTPException(503, state["reason"])
        data = await bounded_body(request, registry.max_bytes)
        started = clock()
        try:
            mime = request.headers.get("content-type", "")
            result = await asyncio.to_thread(backend.transcribe, data, mime)
        except TakeFailed as exc:
            raise HTTPException(exc.status, str(exc)) from exc
        except TranscriberUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        return {"preset": name, "text": result.text, "language": result.language,
                "duration": result.duration, "segments": list(result.segments),
                "latency_ms": round((clock() - started) * 1000)}

    return router
