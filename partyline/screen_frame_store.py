"""Persist screen frames as line-scoped media without posting chat messages."""

import asyncio
import uuid

from .media import prepared_files


async def store_frame(store, conv_id: str, data: bytes, mime: str, name: str = "screen-frame",
                      title: str = "Screen frame"):
    """Use a private negative media group, outside the positive chat message IDs."""
    prepared = await asyncio.to_thread(prepared_files, [(data, name, mime)])
    group = -(uuid.uuid4().int % (2**63 - 1)) - 1
    refs = await asyncio.to_thread(store.store, conv_id, group, prepared, title, None)
    return refs[0]


async def frame_reference(store, share, sender, frame, data, mime, marked=False):
    """Reuse the last identical image delivered to this agent in this share."""
    async with share.frame_lock:
        previous = share.agent_frames.get(sender)
        geometry = (frame.region, frame.out_width, frame.out_height, marked)
        if previous and previous[0] == data and previous[1] == geometry:
            return previous[2], True
        ref = await store_frame(store, share.conv_id, data, mime)
        share.agent_frames[sender] = (data, geometry, ref)
        return ref, False
