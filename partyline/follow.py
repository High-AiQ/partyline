"""Human-owned lead subscription for one receipt-capable process per line."""

import sqlite3

from fastapi import HTTPException

from .adapter_capabilities import adapter_completion
from .attachment_commands import validated_attachment_command
from .attachment_view import attachment_response
from .auth_guard import request_principal
from .contracts import AttachmentEvent
from .presence import RECEIPT


def require_follow_allowed(request, adapter: str, enabled: bool) -> None:
    """Only a human may change follow, and only receipt adapters may enable it."""
    if request_principal(request).kind != "user":
        raise HTTPException(403, "only a human can change follow mode")
    if enabled and adapter_completion(adapter) != RECEIPT:
        raise HTTPException(400, "follow requires an adapter with turn-end receipts")


def slot_conflict(db, conv_id: str) -> HTTPException:
    holder = db.follow_holder(conv_id)
    detail = f"follow is already held by @{holder}" if holder else "follow is already held"
    return HTTPException(409, detail)


def add_attachment_with_follow(
    db, att_id: str, conv_id: str, name: str, adapter: str,
    command: list[str], cwd: str, runtime_owner: str, follow: bool,
):
    if not follow:
        return db.add_attachment(
            att_id, conv_id, name, adapter, command, cwd, runtime_owner, False
        )
    try:
        return db.add_attachment(
            att_id, conv_id, name, adapter, command, cwd, runtime_owner, follow
        )
    except sqlite3.IntegrityError:
        raise slot_conflict(db, conv_id) from None


async def patch_attachment(
    request, att_id: str, body, *, runtime, adapters, metadata, require_loopback
):
    """Apply one named attachment change and publish the authoritative row."""
    att = runtime.db.get_attachment(att_id)
    if not att:
        raise HTTPException(404)
    if body.follow is not None:
        require_follow_allowed(request, att["adapter"], body.follow)
        try:
            updated = runtime.db.set_attachment_follow(att_id, body.follow)
        except sqlite3.IntegrityError:
            raise slot_conflict(runtime.db, att["conv_id"]) from None
        if updated is None:
            raise HTTPException(404)
    else:
        require_loopback(request)
        if att_id in runtime.live or att["status"] not in ("exited", "detached"):
            raise HTTPException(409, f"'{att['name']}' must be stopped before editing its command")
        try:
            command = validated_attachment_command(
                att["adapter"], body.command or "", adapters, metadata
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        updated = await runtime.db.update_inactive_attachment_command(att_id, command)
        if updated is None:
            raise HTTPException(409, f"'{att['name']}' became live; refresh and try again")
    response = await attachment_response(updated)
    await runtime.broadcast(att["conv_id"], AttachmentEvent(attachment=response))
    return response
