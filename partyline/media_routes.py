"""REST routes for uploading, listing, and serving persisted images."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from .contracts import ImageRef, ImageUploadResponse, MessageEvent, MessageResponse
from .media import MediaError, MediaStore, prepared_images, validated_metadata
from .runtime import handle_error


def _http(exc: MediaError) -> HTTPException:
    return HTTPException(exc.status_code, exc.detail)


def _sender_type(runtime, conv_id: str, sender: str) -> str:
    needle = sender.lower()
    for attachment in runtime.db.list_attachments(conv_id):
        if attachment["name"].lower() == needle and attachment["status"] in (
            "starting",
            "running",
        ):
            return "agent"
    return "human"


def _digest_line(ref: ImageRef, base: str) -> str:
    title = ref.title or ("image" if not ref.description else None)
    label = " — ".join(part for part in (title, ref.description) if part)
    return f"📷 {label} · {ref.width}×{ref.height} · thumb: {base}/api/media/{ref.id}/thumb"


def _digest_body(caption: str, refs: list[ImageRef], base: str) -> str:
    lines = [caption.strip()] if caption.strip() else []
    lines.extend(_digest_line(ref, base) for ref in refs)
    return "\n".join(lines)


def media_router(runtime, store: MediaStore) -> APIRouter:
    """Bind image routes to one runtime and its media store."""
    router = APIRouter()

    def require_line(conv_id: str, *, writing: bool):
        conv = runtime.db.get_conversation(conv_id)
        if not conv:
            raise HTTPException(404)
        if writing and conv["archived_at"]:
            raise HTTPException(409, "restore the line before adding images")
        return conv

    @router.post(
        "/api/conversations/{conv_id}/images", response_model=ImageUploadResponse
    )
    async def upload_images(
        conv_id: str,
        request: Request,
        # FastAPI declares multipart fields as call-valued defaults; that is
        # the framework's binding syntax, not an accidental mutable default.
        file: list[UploadFile] | None = File(None),  # noqa: B008
        sender: str | None = Form(None),
        title: str | None = Form(None),
        description: str | None = Form(None),
        body: str | None = Form(None),
    ):
        require_line(conv_id, writing=True)
        who = (sender or "").strip()
        problem = handle_error(who)
        if problem:
            raise HTTPException(400, problem)
        try:
            prepared = prepared_images([await uploaded.read() for uploaded in file or []])
            title, description = validated_metadata(title, description)
        except MediaError as exc:
            raise _http(exc) from exc
        kind = _sender_type(runtime, conv_id, who)
        placeholder = runtime.db.add_message(conv_id, who, kind, "")
        try:
            store.store(conv_id, placeholder["id"], prepared, title, description)
        except MediaError as exc:
            runtime.db._exec("DELETE FROM messages WHERE id=?", (placeholder["id"],))
            raise _http(exc) from exc
        except Exception:
            runtime.db._exec("DELETE FROM messages WHERE id=?", (placeholder["id"],))
            raise
        base = str(request.base_url).rstrip("/")
        absolute = store.for_message(placeholder["id"], base)
        relative = store.for_message(placeholder["id"])
        caption = _digest_body(body or "", absolute, base)
        runtime.db._exec(
            "UPDATE messages SET body=? WHERE id=?", (caption, placeholder["id"])
        )
        stored = {**placeholder, "body": caption, "images": relative}
        message = MessageResponse.model_validate(
            {**placeholder, "body": caption, "images": absolute}
        )
        await runtime.broadcast(conv_id, MessageEvent(message=MessageResponse.model_validate(stored)))
        await runtime.route_mentions(conv_id, stored)
        return {"message": message, "images": absolute}

    @router.get("/api/conversations/{conv_id}/images", response_model=list[ImageRef])
    async def list_images(conv_id: str, request: Request):
        require_line(conv_id, writing=False)
        return store.list_conversation(conv_id, str(request.base_url).rstrip("/"))

    @router.get("/api/media/{image_id}/{variant}")
    async def serve_media(image_id: str, variant: str):
        if variant not in ("original", "thumb"):
            raise HTTPException(404)
        located = store.file_for(image_id, variant)
        if located is None:
            raise HTTPException(404)
        path, mime = located
        return FileResponse(
            path,
            media_type=mime,
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    return router
