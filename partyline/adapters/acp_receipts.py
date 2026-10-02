"""Marker-bound receipt delivery for newline-framed ACP prompts."""

from __future__ import annotations


async def deliver_prompt(adapter, messages: list[dict]) -> bool | None:
    """Send one ACP prompt and leave ids uncredited until its transcript record."""
    if not adapter._session_id:
        raise RuntimeError("ACP session is not ready")
    adapter._silent_until_wake = False
    digest = adapter.format_digest(messages)
    marker = adapter._new_paste_marker()
    tracked = adapter._track_jsonl_paste(digest, messages, marker)
    try:
        await adapter._send_request("session/prompt", {
            "sessionId": adapter._session_id,
            "prompt": [{"type": "text", "text": f"{marker}\n\n{digest}"}],
        })
    except BaseException:
        if tracked:
            adapter._jsonl_receipts = [
                item for item in adapter._jsonl_receipts if item["marker"] != marker
            ]
        raise
    return False if tracked else None
