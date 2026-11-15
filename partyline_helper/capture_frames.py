"""Serialize and send captured desktop frames for a consented screen share."""
from .desktop import pointer_state
from .images import encode


async def frame(session, request_id=None, force=False):
    async with session.frame_lock:
        share = session.share
        if not share or not session.accepted or session.last_capture_image is None:
            return
        if (not force and session.last_frame_at is not None
                and session.clock() - session.last_frame_at < 1 / share["max_fps"]):
            if request_id is not None:
                await session.send("error", request_id=request_id,
                                   message="Snap rate limit: wait for the next frame")
            return
        await send(session, session.last_capture_image, share["region"], share, request_id)


async def frame_from_capture(session, request, image):
    async with session.frame_lock:
        if session.share is not request or not session.accepted:
            return
        session.last_capture_image = image
        await send(session, image, request["region"], request, None)


async def send(session, image, region, share, request_id):
    pointer = pointer_state(session.desktop, region)
    binary, width, height, mime = encode(image, share["long_edge"])
    await session.send("frame", binary, share_id=share["share_id"], request_id=request_id,
                       ts_ms=int((session.clock() - session.started) * 1000), region=region,
                       out_width=width, out_height=height, pointer=pointer, mime=mime)
    session.last_uia_frame = (dict(region), width, height)
    session.last_frame_at = session.clock()
