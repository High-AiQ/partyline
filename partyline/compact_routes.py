"""REST command for compacting a live adapter's own conversation context."""

from fastapi import FastAPI, HTTPException

from .contracts import CompactResponse
from .presence import RECEIPT


async def request_compact(runtime, presence, att_id: str) -> dict:
    """Queue or send the exact manifest paste for one live attachment."""
    adapter = runtime.live.get(att_id)
    if adapter is None:
        raise HTTPException(404, "attachment is not live")
    paste = adapter.att.get("adapter_metadata", {}).get("compact_paste")
    if not isinstance(paste, str) or not paste.strip():
        raise HTTPException(409, "adapter does not expose a compact command")

    async def send() -> None:
        await adapter.send_keys(paste)

    working = presence.completion(att_id) == RECEIPT and presence.is_working(att_id)
    queued = await presence.queue.compact(att_id, send, working)
    return {"ok": True, "queued": queued}


def register_compact_route(app: FastAPI, runtime, presence) -> None:
    @app.post("/api/attachments/{att_id}/compact", response_model=CompactResponse)
    async def compact_attachment(att_id: str):
        return await request_compact(runtime, presence, att_id)
