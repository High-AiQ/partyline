"""Process-facing notices for changes in screen access."""

from .screen_connections import notice
from .screen_grants import GRANTS


def _window_share_on_line(hub, conv_id):
    grants = hub.runtime.db._exec(GRANTS + " AND a.conv_id=?", (conv_id,)).fetchall()
    return any(grant["device_id"] in hub.devices for grant in grants)


async def share_started(hub, share, device):
    if share.share_id in hub.walkthroughs.items:
        return
    if share.start_notice_sent:
        return
    share.start_notice_sent = True
    media = f"first frame: media {share.first_media.id} (get_media). " if share.first_media else ""
    window_tools = _window_share_on_line(hub, share.conv_id)
    tools = "screen_frame; screen_elements summary/find/ls/text" if window_tools else "screen_frame"
    device_name = device.get("name", "their screen")
    text = (f"@all {share.requested_by} started sharing {device_name}; {media}{tools}. "
            "People sharing usually want the processes on this line to look now: call screen_frame.")
    if not window_tools:
        text += " For text or elements, ask the person to share a single window."
    await notice(hub, share.conv_id, text)


async def share_stopped(hub, share, device, *, last_frame_saved=False):
    if share.share_id in hub.walkthroughs.items:
        return
    media = (f"; last frame: media {share.last_media.id}"
             if last_frame_saved and share.last_media else "")
    device_name = device.get("name", "their screen") if device else "their screen"
    await notice(hub, share.conv_id,
                 f"@all {share.requested_by} stopped sharing {device_name}{media}; "
                 "screen_frame is no longer available.")
