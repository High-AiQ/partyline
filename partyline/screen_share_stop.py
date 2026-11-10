"""Stop a screen share even when saving its final frame or notice fails."""

import logging

from .screen_requests import end_share
from .screen_share_frames import store_last_frame
from .screen_share_notices import share_stopped

logger = logging.getLogger(__name__)


async def stop_share(hub, share, reason):
    status = share.status
    if status == "stopping":
        return
    walkthrough = share.share_id in hub.walkthroughs.items
    share.status = "stopping"
    last_frame_saved = False
    try:
        if status == "active" and not walkthrough:
            async with share.evidence_lock:
                try:
                    last_frame_saved = await store_last_frame(hub, share)
                except Exception:
                    logger.exception("could not save the final frame for screen share %s",
                                     share.share_id)
    finally:
        hub.walkthroughs.share_ended(share.share_id)
        end_share(hub, share)
        try:
            await hub.control.end(share, reason)
        except Exception:
            logger.exception("could not finish control cleanup for screen share %s", share.share_id)
        device = hub.devices.get(share.device_id)
        if device:
            try:
                await device["socket"].send_json({"type": "stop_share", "share_id": share.share_id})
            except Exception:
                pass
        if status == "waiting" and device:
            view = hub._share_view(share, device)
            view["share"]["status"] = "declined"
            view["share"]["reason"] = reason
            await hub._line_event(share.conv_id, view)
        else:
            await hub._line_event(share.conv_id, {"type": "screen_share", "share": None})
    if status == "active" and not walkthrough:
        try:
            await share_stopped(hub, share, hub.devices.get(share.device_id),
                                last_frame_saved=last_frame_saved)
        except Exception:
            logger.exception("could not post the stop notice for screen share %s", share.share_id)
