"""REST routes for uploading, listing, and serving persisted files."""

from __future__ import annotations

import asyncio
import hashlib

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from .auth_guard import request_principal
from .contracts import FileRef, FileUploadResponse, MessageEvent, MessageResponse
from .hierarchy import ancestors, stamp_source
from .idempotent_posts import (
    claim_key,
    original_for_key,
    principal_identity,
    remember_key,
)
from .media import MediaError, MediaStore, prepared_files, validated_metadata
from .media_digest import digest_body
from .media_files import MAX_FILES_PER_POST
from .media_rows import VARIANTS
from .transcribe_routes import transcribe_router
from .asr_presets import shared_registry
from .asr_settings_routes import asr_settings_router
from .machine_scope import allows, deny_unless, is_human
from .upload_scope import UPLOAD_ONLY_CAPTION_REFUSAL


def deny_unless_media_read(db, principal, conv_id: str) -> None:
    """Allow ancestor media without granting access to ancestor messages."""
    if (principal.kind == "machine" and principal.conv_id
            and conv_id in ancestors(db, principal.conv_id)):
        return
    deny_unless(db, principal, conv_id, "read")


def handed_to(db, principal, file_id: str) -> bool:
    """A process may read a file that a relayed private copy put in front of it.

    A brief attached on the root line and relayed to a child captain named
    this file in that captain's own digest; refusing the fetch sent the root
    captain copying the document to disk by hand.
    """
    if principal.kind != "machine" or not principal.attachment_id:
        return False
    row = db._exec(
        "SELECT 1 FROM messages WHERE audience_attachment_id=? AND body LIKE ? LIMIT 1",
        (principal.attachment_id, f"%/api/media/{file_id}/%"),
    ).fetchone()
    return row is not None

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
        client_key: str | None = Form(None, max_length=64),
        include_screen: bool = Form(False),
    ):
        require_line(conv_id, writing=True)
        principal = request_principal(request)
        deny_unless(runtime.db, principal, conv_id, "upload")
        if include_screen:
            deny_unless(runtime.db, principal, conv_id, "read")
        if body and body.strip() and not allows(runtime.db, principal, conv_id, "write"):
            raise HTTPException(403, UPLOAD_ONLY_CAPTION_REFUSAL)
        if body and body.strip() and is_human(principal) and not any(
            attachment["status"] in ("starting", "running")
            for attachment in runtime.db.list_attachments(conv_id)
        ):
            raise HTTPException(409, "attach a process to this line before sending")
        who = principal.name
        caller_id = principal_identity(principal)
        hub = getattr(request.app.state, "screen_hub", None)
        bound_share = hub.shares.get(conv_id) if hub and include_screen else None
        if bound_share and bound_share.share_id in hub.walkthroughs.items:
            raise HTTPException(409, "screen frames are unavailable while a walkthrough is in progress")
        upload_key = (
            "upload:" + hashlib.sha256(client_key.encode()).hexdigest()
            if client_key else None
        )
        async def save_or_replay():
            if upload_key and caller_id and (original := original_for_key(
                runtime.db, caller_id, upload_key, conv_id
            )) is not None:
                files = store.for_message(original["id"])
                replayed = MessageResponse.model_validate({
                    **original, "files": files, "replayed": True,
                })
                return {"message": replayed, "files": files}
            try:
                # Preparation decodes bytes and may fall back to an ffmpeg
                # subprocess with a minute-long timeout — none of that may run
                # on the event loop every wake and WebSocket depends on.
                uploads = await _uploads(file)
                current_share = hub.shares.get(conv_id) if hub else None
                share = current_share
                if include_screen and current_share is not bound_share:
                    share = None
                selected = []
                latest_ts = share.frames[-1].ts_ms if share and share.frames else None
                if include_screen and share and share.status == "active":
                    from .screen_frames import frames_since, pick_distinct
                    identity = caller_id or who
                    seen = share.attached.get(identity, set())
                    since = share.last_message_ts.get(identity, -1)
                    fresh = [frame for frame in frames_since(share, since) if frame.sequence not in seen]
                    selected = pick_distinct(fresh, 3)
                    if not selected and share.frames and share.frames[-1].sequence not in seen:
                        selected = [share.frames[-1]]
                    selected = selected[:max(0, MAX_FILES_PER_POST - len(uploads))]
                    uploads.extend((f.data, "screen-frame", f.mime) for f in selected)
                if not uploads and include_screen and body and body.strip():
                    from .message_routing import post_identified
                    message = await post_identified(runtime, conv_id, principal, body)
                    return {"message": message, "files": []}
                prepared = await asyncio.to_thread(prepared_files, uploads)
                prepared_title, prepared_description = validated_metadata(title, description)
            except MediaError as exc:
                raise _http(exc) from exc
            kind = "agent" if principal.kind == "machine" else "human"
            placeholder = runtime.db.add_message(conv_id, who, kind, "")
            placeholder = {
                **placeholder,
                **stamp_source(runtime.db, placeholder["id"], principal),
            }
            try:
                store.store(
                    conv_id, placeholder["id"], prepared,
                    prepared_title, prepared_description,
                )
            except MediaError as exc:
                runtime.db._exec("DELETE FROM messages WHERE id=?", (placeholder["id"],))
                raise _http(exc) from exc
            except Exception:
                runtime.db._exec("DELETE FROM messages WHERE id=?", (placeholder["id"],))
                raise
            if share and latest_ts is not None:
                share.last_message_ts[caller_id or who] = latest_ts
                seen = share.attached.setdefault(caller_id or who, set())
                seen.update(frame.sequence for frame in selected)
            # Host-relative everywhere: request.base_url is whatever the caller dialled,
            # and that was 0.0.0.0 often enough to hand processes links nobody can open.
            relative = absolute = store.for_message(placeholder["id"])
            caption = digest_body(body or "", relative, "")
            runtime.db._exec(
                "UPDATE messages SET body=? WHERE id=?", (caption, placeholder["id"])
            )
            if upload_key and caller_id:
                remember_key(runtime.db, caller_id, upload_key, conv_id, placeholder["id"])
            stored = {**placeholder, "body": caption, "files": relative}
            message = MessageResponse.model_validate(
                {**placeholder, "body": caption, "files": absolute}
            )
            await runtime.broadcast(
                conv_id, MessageEvent(message=MessageResponse.model_validate(stored))
            )
            await runtime.route_mentions(conv_id, stored)
            return {"message": message, "files": absolute}

        async def save_locked_key():
            if upload_key and caller_id:
                async with claim_key(runtime.db, caller_id, conv_id, upload_key):
                    return await save_or_replay()
            return await save_or_replay()

        if bound_share:
            lock = bound_share.locks.setdefault(caller_id or who, asyncio.Lock())
            async with lock:
                return await save_locked_key()
        return await save_locked_key()

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
        deny_unless_media_read(runtime.db, request_principal(request), conv_id)
        return store.list_conversation(conv_id)

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
    async def serve_media(request: Request, file_id: str, variant: str):
        if variant not in VARIANTS:
            raise HTTPException(404)
        owned = runtime.db._exec(
            "SELECT conv_id FROM images WHERE id=?", (file_id,)
        ).fetchone()
        if owned is not None and not handed_to(runtime.db, request_principal(request), file_id):
            deny_unless_media_read(runtime.db, request_principal(request), owned["conv_id"])
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

    router.include_router(transcribe_router(runtime, lambda: shared_registry(runtime.db)))
    router.include_router(asr_settings_router(runtime))
    return router
