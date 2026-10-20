"""Start an already-reserved attachment through the regular PTY seam."""

import asyncio
import logging

from fastapi import HTTPException

from .agent_connection import provision_connection
from .adapter_capabilities import adapter_completion, compaction_detect
from .attachment_view import attach_memory_usage, attachment_response
from .auth_store import ensure_api_token
from .compaction_events import transcript_compaction_callback
from .fence import FenceUnavailable
from .process_memory import MemoryScopeUnavailable
from .process_incidents import exit_callback
from .preset_traits import auto_compact_tokens_for
from .fence_protect import database_paths, protected_repo_roots
from .hook_routes import surface_attention
from .review_worktrees import list_review_worktrees
from .scratch_worktrees import list_scratch_worktrees
from .role_delivery import bind_role_delivery
from .write_set_routes import load_write_grants
from .resume_backlog import addressed_backlog
from .resource_budget import format_limit, settings

logger = logging.getLogger(__name__)


def prepare_attachment(att, runtime, hook_url, checkpoint):
    conv = runtime.db.get_conversation(att["conv_id"])
    att["api_token"] = ensure_api_token(runtime.db, att["id"])
    att["memory_limit"] = att.get("memory_limit") or format_limit(
        settings(runtime.db)["default_process_memory_bytes"]
    )
    att["global_prose"] = runtime.db.get_setting("global_prose")
    att["conv_name"], att["topic"] = conv["name"], conv["topic"]
    att["hook_url"] = hook_url(att["id"], att["runtime_owner"])
    load_write_grants(runtime.db, att)
    att["review_worktrees"] = list_review_worktrees(runtime.db, att["conv_id"])
    att["scratch_worktrees"] = list_scratch_worktrees(runtime.db, att["conv_id"])
    att["protected_roots"] = protected_repo_roots(runtime.db)
    att["db_paths"] = database_paths(runtime.db)
    provision_connection(runtime.db.path, att)
    att["digest_rider"] = lambda: ""  # role delivery layers the goal and staffing on top
    bind_role_delivery(runtime.db, att, runtime)
    att["fresh_checkpoint"] = checkpoint
    att["startup_attention"] = lambda prompt: surface_attention(runtime, att, prompt)
    att["on_process_exit"] = exit_callback(runtime, att)
    # The preset's explicit auto-compact threshold (§2.13), re-read on every
    # start so a resume picks up a changed preset; 0 lets the CLI default.
    att["auto_compact_tokens"] = auto_compact_tokens_for(runtime.db, att)
    if compaction_detect(att) == "transcript":
        # Claude gets its rebrief from hook stdout; a transcript-only
        # harness gets it as a private wake, and the adapter calls this
        # when its own tail sees the compaction (2.13, §5-generalised).
        att["on_compaction"] = transcript_compaction_callback(runtime, att)


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


async def start_attachment(att, *, runtime, presence, make_adapter, hook_url,
                           checkpoint="", fresh=False):
    ident, conv_id, owner = att["id"], att["conv_id"], att["runtime_owner"]
    try:
        prepare_attachment(att, runtime, hook_url, checkpoint)
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
