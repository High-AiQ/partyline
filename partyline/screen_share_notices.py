"""Process-facing notices for changes in screen access."""

from .screen_connections import notice


async def share_started(hub, share, device):
    if share.share_id in hub.walkthroughs.items:
        return
    text = (f"@all {share.requested_by} is sharing {device['name']}; screen_frame; "
            "screen_elements summary/find/ls/text; act with ids. Page offset/next_offset; "
            "refresh after changes (ids may be stale).")
    await notice(hub, share.conv_id, text)
