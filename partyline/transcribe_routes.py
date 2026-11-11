"""REST surface for voice input: preset listing and one-shot transcription."""

from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from .auth_guard import request_principal
from .machine_scope import deny_unless
from .walkthrough_transcribe import transcribe_walkthrough
from .transcript import TakeFailed, TranscriberUnavailable, WhisperRetired, segments_to_vtt

logger = logging.getLogger(__name__)


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
    utterance: bool = False
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


def _log_take(conv_id: str, preset: str, size: int, started: float, *, result=None, error: str = "") -> None:
    """One line per take: outcome, sizes and timing, never the words themselves."""
    seconds = time.monotonic() - started
    if error:
        # Callers pass a category or fixed copy. Provider messages can quote speech.
        logger.warning("transcribe line=%s preset=%s bytes=%d took=%.2fs error=%s",
                       conv_id, preset, size, seconds, error)
    else:
        logger.info("transcribe line=%s preset=%s bytes=%d audio=%.1fs took=%.2fs chars=%d%s",
                    conv_id, preset, size, result.duration, seconds, len(result.text),
                    "" if result.text.strip() else " empty=true")


def transcribe_router(runtime, get_registry) -> APIRouter:
    """``get_registry`` is a thunk so tests can swap in fakes."""
    router = APIRouter()

    @router.get("/api/transcribe/presets", response_model=PresetListing)
    def presets() -> dict:
        return get_registry().listing()

    @router.post("/api/conversations/{conv_id}/transcribe", response_model=TranscribeResponse,
                 response_model_exclude_unset=True)
    async def transcribe(conv_id: str, request: Request, preset: str | None = None,
                         format: str = "json", walkthrough: bool = False):
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
        name = preset or registry.default
        started = time.monotonic()
        try:
            if walkthrough:
                result = await asyncio.to_thread(transcribe_walkthrough, backend, data, mime)
            else:
                result = await asyncio.to_thread(backend.transcribe, data, mime)
        except TakeFailed as exc:  # this take only: the mic must stay usable
            detail = str(exc) if isinstance(exc, WhisperRetired) else f"take-failed status={exc.status}"
            _log_take(conv_id, name, len(data), started, error=detail)
            raise HTTPException(exc.status, str(exc)) from exc
        except TranscriberUnavailable as exc:
            _log_take(conv_id, name, len(data), started, error="unavailable")
            raise HTTPException(503, str(exc)) from exc
        _log_take(conv_id, name, len(data), started, result=result)
        if format == "vtt":
            return PlainTextResponse(segments_to_vtt(result.segments), media_type="text/vtt")
        return {"text": result.text, "language": result.language, "duration": result.duration,
                "segments": list(result.segments)}

    return router
