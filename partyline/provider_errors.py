"""Surface adapter-confirmed provider failures without a false stall report."""

from .orchestrator_notices import notify_root
from .orchestrator_store import task
from .preset_traits import match_preset


def provider_error_callback(runtime, att):
    notified = False

    async def noted(cause, fresh):
        nonlocal notified
        if fresh:
            await runtime.post_message(
                att['conv_id'], 'system', 'system',
                f"⚠ @{att['name']}: model provider error — {cause}")
        if notified:
            return
        notified = True
        row = task(runtime.db, att['conv_id'])
        if row:
            preset = match_preset(att, runtime.db.list_presets())
            name = preset['name'] if preset else att.get('preset') or 'unmatched preset'
            await notify_root(runtime, row,
                              f"model provider error for preset {name}: {cause}. "
                              "Stop staffing this preset until its provider recovers.")
    return noted
