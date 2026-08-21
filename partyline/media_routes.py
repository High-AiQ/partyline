"""REST routes for uploading, listing, and serving persisted files."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from .auth_guard import request_principal
from .contracts import FileRef, FileUploadResponse, MessageEvent, MessageResponse
from .media import MediaError, MediaStore, prepared_files, validated_metadata
from .media_digest import digest_body
from .media_rows import VARIANTS

# Inline is an allowlist: anything a browser might execute as script from our
# own origin — html, xhtml, xml, svg — is served as a download instead.
_INLINE_PREFIXES = ("image/", "audio/", "video/")
_INLINE_EXACT = frozenset({"application/pdf", "text/plain"})
_NEVER_INLINE = frozenset({"image/svg+xml"})


def _disposition(mime: str) -> str:
    if mime in _NEVER_INLINE:
        return "attachment"
    if mime in _INLINE_EXACT or mime.startswith(_INLINE_PREFIXES):
        return "inline"
    return "attachment"


def _http(exc: MediaError) -> HTTPException:
    return HTTPException(exc.status_code, exc.detail)


async def _uploads(
    file: list[UploadFile] | None,
) -> list[tuple[bytes, str | None, str | None]]:
    return [
        (await uploaded.read(), uploaded.filename, uploaded.content_type)
        for uploaded in file or []
    ]


def media_router(runtime, store: MediaStore) -> APIRouter:
    """Bind file routes to one runtime and its media store."""
    router = APIRouter()

    def require_line(conv_id: str, *, writing: bool):
        conv = runtime.db.get_conversation(conv_id)
        if not conv:
            raise HTTPException(404)
        if writing and conv["archived_at"]:
            raise HTTPException(409, "restore the line before adding files")
        return conv

    async def upload_files(
        conv_id: str,
        request: Request,
        # FastAPI declares multipart fields as call-valued defaults; that is
        # the framework's binding syntax, not an accidental mutable default.
        file: list[UploadFile] | None = File(None),  # noqa: B008
        title: str | None = Form(None),
        description: str | None = Form(None),
        body: str | None = Form(None),
    ):
        require_line(conv_id, writing=True)
        # Sender identity comes from the credential, never a form field.
        principal = request_principal(request)
        who = principal.name
        try:
            prepared = prepared_files(await _uploads(file))
            title, description = validated_metadata(title, description)
        except MediaError as exc:
            raise _http(exc) from exc
        kind = "agent" if principal.kind == "machine" else "human"
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
        caption = digest_body(body or "", absolute, base)
        runtime.db._exec(
            "UPDATE messages SET body=? WHERE id=?", (caption, placeholder["id"])
        )
        stored = {**placeholder, "body": caption, "files": relative}
        message = MessageResponse.model_validate(
            {**placeholder, "body": caption, "files": absolute}
        )
        await runtime.broadcast(
            conv_id, MessageEvent(message=MessageResponse.model_validate(stored))
        )
        await runtime.route_mentions(conv_id, stored)
        return {"message": message, "files": absolute}

    router.add_api_route(
        "/api/conversations/{conv_id}/files",
        upload_files,
        methods=["POST"],
        response_model=FileUploadResponse,
        name="upload_files",
    )
    router.add_api_route(
        "/api/conversations/{conv_id}/images",
        upload_files,
        methods=["POST"],
        response_model=FileUploadResponse,
        name="upload_images",
    )

    async def list_files(conv_id: str, request: Request):
        require_line(conv_id, writing=False)
        return store.list_conversation(conv_id, str(request.base_url).rstrip("/"))

    router.add_api_route(
        "/api/conversations/{conv_id}/files",
        list_files,
        methods=["GET"],
        response_model=list[FileRef],
        name="list_files",
    )
    router.add_api_route(
        "/api/conversations/{conv_id}/images",
        list_files,
        methods=["GET"],
        response_model=list[FileRef],
        name="list_images",
    )

    @router.get("/api/media/{file_id}/{variant}")
    async def serve_media(file_id: str, variant: str):
        if variant not in VARIANTS:
            raise HTTPException(404)
        located = store.file_for(file_id, variant)
        if located is None:
            raise HTTPException(404)
        path, mime, filename = located
        # Private: media URLs may carry a ?token= (an <img> tag cannot send a
        # header), and a shared cache must never store a tokened response.
        return FileResponse(
            path,
            media_type=mime,
            filename=filename or path.name,
            content_disposition_type=_disposition(mime),
            headers={
                "Cache-Control": "private, max-age=31536000, immutable",
                "X-Content-Type-Options": "nosniff",
            },
        )

    return router
