"""REST surface for voice input: preset listing and one-shot transcription."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from .auth_guard import request_principal
from .machine_scope import deny_unless
from .transcript import TakeFailed, TranscriberUnavailable, segments_to_vtt


class PresetStatus(BaseModel):
    name: str
    kind: str
    available: bool
    reason: str | None = None
    model: str | None = None


class PresetListing(BaseModel):
    default: str
    presets: list[PresetStatus]


class TranscribeSegment(BaseModel):
    start: float
    end: float
    text: str


class TranscribeResponse(BaseModel):
    text: str
    language: str
    duration: float
    segments: list[TranscribeSegment] = []


async def bounded_body(request: Request, limit: int) -> bytes:
    too_big = HTTPException(413, f"audio is larger than {limit // (1024 * 1024)} MB")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise too_big
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise too_big
        chunks.append(chunk)
    if not size:
        raise HTTPException(400, "no audio received")
    return b"".join(chunks)


def transcribe_router(runtime, get_registry) -> APIRouter:
    """``get_registry`` is a thunk so tests can swap in fakes."""
    router = APIRouter()

    @router.get("/api/transcribe/presets", response_model=PresetListing)
    def presets() -> dict:
        return get_registry().listing()

    @router.post("/api/conversations/{conv_id}/transcribe", response_model=TranscribeResponse)
    async def transcribe(conv_id: str, request: Request, preset: str | None = None, format: str = "json"):
        # Audio is read into memory and handed on as bytes: a multipart upload
        # would spool to a temp file, and a take must never touch the disk.
        principal = request_principal(request)
        deny_unless(runtime.db, principal, conv_id, "write")
        if format not in ("json", "vtt"):
            raise HTTPException(400, "format must be json or vtt")
        registry = get_registry()
        try:
            backend = registry.get(preset)
        except KeyError:
            raise HTTPException(404, f"no speech preset named {preset!r}") from None
        state = backend.status()
        if not state["available"]:
            raise HTTPException(503, state["reason"])
        data = await bounded_body(request, registry.max_bytes)
        mime = request.headers.get("content-type", "")
        try:
            result = await asyncio.to_thread(backend.transcribe, data, mime)
        except TakeFailed as exc:  # this take only: the mic must stay usable
            raise HTTPException(exc.status, str(exc)) from exc
        except TranscriberUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        if format == "vtt":
            return PlainTextResponse(segments_to_vtt(result.segments), media_type="text/vtt")
        return {"text": result.text, "language": result.language, "duration": result.duration,
                "segments": list(result.segments)}

    return router
