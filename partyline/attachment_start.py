"""Start an already-reserved attachment through the regular PTY seam."""

import asyncio

from fastapi import HTTPException

from .adapter_capabilities import adapter_completion
from .attachment_view import attachment_response
from .auth_store import ensure_api_token


def prepare_attachment(att, runtime, tasks, hook_url, checkpoint):
    conv = runtime.db.get_conversation(att["conv_id"])
    att["api_token"] = ensure_api_token(runtime.db, att["id"])
    att["conv_name"], att["topic"] = conv["name"], conv["topic"]
    att["hook_url"] = hook_url(att["id"], att["runtime_owner"])
    att["digest_rider"] = lambda: tasks.rider(att["conv_id"])
    att["fresh_checkpoint"] = checkpoint


async def rollback_start(runtime, att):
    """Never erase a reservation until its possible process has stopped."""
    ident = att["id"]
    if adapter := runtime.live.get(ident):
        try:
            await adapter.stop()
        except Exception:
            # Keep the card and adapter reachable for an explicit detach retry.
            await runtime.broadcast_attachment(att["conv_id"], ident)
            raise
        runtime.live.pop(ident, None)
    await runtime.db.set_attachment_status_async(ident, "exited", att["runtime_owner"])


async def start_attachment(att, *, runtime, presence, tasks, make_adapter, hook_url,
                           checkpoint="", fresh=False):
    ident, conv_id, owner = att["id"], att["conv_id"], att["runtime_owner"]
    try:
        prepare_attachment(att, runtime, tasks, hook_url, checkpoint)
        adapter = make_adapter(
            att["adapter"], att,
            presence.posting(conv_id, ident, runtime.post_callback(ident, conv_id, owner)),
            presence.statusing(
                conv_id, ident, runtime.status_callback(ident, conv_id, owner), att["name"]),
            on_cli_session=lambda session: runtime.db.set_cli_session(ident, session, owner),
        )
        # Own cleanup even if start fails after creating a PTY but before returning.
        runtime.live[ident] = adapter
        await adapter.start()
        runtime.live[ident] = presence.watch(
            adapter, conv_id, ident, adapter_completion(att["adapter"]),
            *runtime.held_wake_hooks(conv_id, ident, att["name"]),
        )
        await announce_attachment(runtime, att, fresh=fresh)
        return await attachment_response(runtime.db.get_attachment(ident))
    except (Exception, asyncio.CancelledError) as exc:
        await rollback_start(runtime, att)
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise HTTPException(500, f"failed to spawn: {exc}") from exc


async def announce_attachment(runtime, att, *, fresh):
    action = "started fresh; previous session not resumed" if fresh else "joined"
    await runtime.post_message(
        att["conv_id"], "system", "system",
        f"@{att['name']} {action} · `{' '.join(att['command'])}` · "
        f"{att['cwd']} · session {att['id']}",
    )
