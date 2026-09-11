"""REST command for detaching every live process from one line."""

from fastapi import FastAPI, HTTPException, Request

from .contracts import MessageEvent, MessageResponse
from .auth_guard import request_principal
from .hierarchy import descendants
from .line_process_contracts import CloseProcessesResponse
from .machine_scope import deny_unless


async def detach_attachment(runtime, att_id: str) -> dict:
    """Run the one-jack detach transaction used by both REST commands."""
    att = runtime.db.get_attachment(att_id)
    if not att:
        raise HTTPException(404)
    adapter = runtime.live.pop(att_id, None)
    if adapter:
        await adapter.stop()
        runtime_owner = adapter.att.get("runtime_owner")
    else:
        runtime_owner = att.get("runtime_owner")
    message = await runtime.db.detach_attachment_with_message_async(
        att_id, runtime_owner, f"@{att['name']} detached"
    )
    if message is None:
        raise HTTPException(
            409,
            "the attachment became live in another server generation; refresh and try again",
        )
    await runtime.broadcast(
        att["conv_id"], MessageEvent(message=MessageResponse.model_validate(message))
    )
    return {"ok": True}


def register_line_process_routes(app: FastAPI, runtime) -> None:
    @app.post(
        "/api/conversations/{conv_id}/attachments/close",
        response_model=CloseProcessesResponse,
    )
    async def close_line_processes(request: Request, conv_id: str):
        conversation = runtime.db.get_conversation(conv_id)
        if conversation is None:
            raise HTTPException(404)
        deny_unless(runtime.db, request_principal(request), conv_id, "close")
        if conversation["archived_at"] is not None:
            raise HTTPException(409, "restore the line before closing its processes")
        target_ids = [conv_id, *descendants(runtime.db, conv_id)]
        live = [
            att
            for target_id in target_ids
            for att in runtime.db.list_attachments(target_id)
            if att["status"] in ("starting", "running")
        ]
        for attachment in live:
            await detach_attachment(runtime, attachment["id"])
        return {"ok": True, "stopped": [attachment["name"] for attachment in live]}
