"""Start an already-reserved attachment through the regular PTY seam."""

import asyncio
import logging

from fastapi import HTTPException

from .adapter_capabilities import adapter_completion
from .attachment_wiring import wire_attachment
from .attachment_view import attach_memory_usage, attachment_response
from .fence import FenceUnavailable
from .process_memory import MemoryScopeUnavailable
from .resume_backlog import addressed_backlog

logger = logging.getLogger(__name__)


def prepare_attachment(att, runtime, hook_url, checkpoint):
    wire_attachment(att, runtime, hook_url, checkpoint=checkpoint)


async def rollback_start(runtime, att):
    """Never erase a reservation until its possible process has stopped."""
    ident = att["id"]
    if adapter := runtime.live.get(ident):
        try:
            from .attachment_stop_audit import direct_stop
            direct_stop(ident, "attachment.start_rollback")
            await adapter.stop()
        except Exception:
            # Keep the card and adapter reachable for an explicit detach retry.
            await runtime.broadcast_attachment(att["conv_id"], ident)
            raise
        runtime.live.pop(ident, None)
    await runtime.db.set_attachment_status_async(ident, "exited", att["runtime_owner"])


async def start_attachment(att, *, runtime, presence, make_adapter, hook_url,
                           checkpoint="", fresh=False, staffing_role=None, principal=None,
                           staffing_preset=None, announce=True, rotation=False):
    if staffing_role and not rotation and (principal is None or principal.kind != 'user'):
        from .preset_roles import require_attachment_role, require_named_role
        try:
            if staffing_preset:
                require_named_role(runtime.db, staffing_preset, staffing_role)
            else:
                require_attachment_role(runtime.db, att, staffing_role)
        except HTTPException:
            await rollback_start(runtime, att)
            raise
    ident, conv_id, owner = att["id"], att["conv_id"], att["runtime_owner"]
    try:
        # This path always launches a new CLI session; resumed sessions use attachment_resume.
        from .context_epoch import start_fresh_context
        start_fresh_context(runtime.db, att)
        await asyncio.to_thread(prepare_attachment, att, runtime, hook_url, checkpoint)
        adapter = make_adapter(
            att["adapter"], att,
            presence.posting(conv_id, ident, runtime.post_callback(ident, conv_id, owner)),
            presence.statusing(
                conv_id, ident, runtime.status_callback(ident, conv_id, owner), att["name"]),
            on_cli_session=lambda session: runtime.db.set_cli_session(ident, session, owner),
        )
        # Own cleanup even if start fails after creating a PTY but before returning.
        runtime.live[ident] = adapter
        from .first_hello import mark_pending

        mark_pending(runtime, ident)
        await adapter.start()
        runtime.live[ident] = presence.watch(
            adapter, conv_id, ident, adapter_completion(att["adapter"]),
            *runtime.held_wake_hooks(conv_id, ident, att["name"]),
        )
        from .memory_events import lifecycle_changed
        lifecycle_changed(runtime)
        if announce:  # a rotation says it once, when it stops the old process
            await announce_attachment(runtime, att, fresh=fresh)
        await deliver_since_attach(runtime, ident)
        return attach_memory_usage(
            await attachment_response(runtime.db.get_attachment(ident)),
            runtime.memory_usage.get(ident),
        )
    except FenceUnavailable as exc:
        # Fail closed, loudly: no unconfined fallback exists on purpose.
        await rollback_start(runtime, att)
        raise HTTPException(409, f"write fence unavailable: {exc}") from exc
    except MemoryScopeUnavailable as exc:
        await rollback_start(runtime, att)
        raise HTTPException(
            409, f"process memory limit unavailable: {exc}. Remedy: run partyline "
            "under a systemd user manager",
        ) from exc
    except (Exception, asyncio.CancelledError) as exc:
        await rollback_start(runtime, att)
        if isinstance(exc, asyncio.CancelledError):
            raise
        # The 500 the caller sees is one line; the journal gets the trace.
        logger.exception("start of %s failed", ident)
        raise HTTPException(500, f"failed to spawn: {exc}") from exc


async def deliver_since_attach(runtime, ident):
    """Hand a new process what was said to it while it was starting.

    The join announcement is a system notice and rings nobody, and a mention
    posted before the process was running found no live adapter to wake. Both
    left the process waiting on a message already on its line. The cursor
    starts at the attach, so this is only what came after it, and delivery
    advances it, so nothing arrives twice.
    """
    att = runtime.db.get_attachment(ident)
    adapter = runtime.live.get(ident)
    if att is None or adapter is None or att["status"] != "running":
        return
    if any(m["id"] > att["last_seen"] for m in addressed_backlog(runtime, att)):
        await runtime.deliver_pending(att["conv_id"], att, adapter)


async def announce_attachment(runtime, att, *, fresh):
    action = "started fresh; previous session not resumed" if fresh else "joined"
    await runtime.post_message(
        att["conv_id"], "system", "system",
        f"@{att['name']} {action} · `{' '.join(att['command'])}` · "
        f"{att['cwd']} · session {att['id']}",
    )
