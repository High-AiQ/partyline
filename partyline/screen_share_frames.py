"""Frame delivery and automatic evidence for an active screen share."""

from .screen_frame_store import store_frame
from .screen_frames import BufferedFrame
from .screen_share_notices import share_started


async def add_frame(hub, device, meta, data):
    share = hub._share(meta.share_id, device["id"])
    if not share or share.status != "active" or meta.region.model_dump() != share.region:
        return
    frame = BufferedFrame(data, meta.ts_ms, meta.region.model_dump(),
                          meta.out_width, meta.out_height,
                          meta.pointer.model_dump(exclude_defaults=True) if meta.pointer else None,
                          meta.mime)
    share.add(frame)
    hub.walkthroughs.add(share, frame)
    if share.share_id not in hub.walkthroughs.items:
        async with share.evidence_lock:
            if share.first_media is None:
                share.first_media = await store_frame(hub.media_store, share.conv_id, data, meta.mime)
                share.last_media = share.first_media
                share.last_stored_data = data
            if not share.start_notice_sent:
                await share_started(hub, share, device)
    if meta.request_id:
        entry = hub.snap_waiters.get(meta.request_id)
        if entry and entry[0] is share and not entry[1].done():
            entry[1].set_result(frame)


async def store_last_frame(hub, share):
    if not share.frames or share.share_id in hub.walkthroughs.items:
        return False
    frame = share.frames[-1]
    if frame.data != share.last_stored_data:
        share.last_media = await store_frame(hub.media_store, share.conv_id,
                                             frame.data, frame.mime)
        share.last_stored_data = frame.data
    return share.last_media is not None
