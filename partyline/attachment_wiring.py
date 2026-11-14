"""The one place an attachment's hooks and settings are wired, for a fresh spawn and a resume alike.

A resumed or reattached process used to get its own, shorter copy of this list, and every
hook added to the fresh path was silently missing on the other (turn usage, provider-error
alerts, compaction counting and rotation, the preset's auto-compact threshold, scratch
checkouts, the line topic). Both paths call ``wire_attachment``; the only differences are
named here and pinned by ``tests/test_attachment_wiring_parity.py``.
"""

from .adapter_capabilities import compaction_detect
from .agent_connection import bind_connection_hint, provision_connection
from .auth_store import ensure_api_token, rotate_api_token
from .compaction_events import transcript_compaction_callback
from .fence_protect import database_paths
from .hook_routes import surface_attention
from . import fence_workspaces
from .preset_traits import auto_compact_tokens_for
from .process_incidents import exit_callback
from .provider_errors import provider_error_callback
from .resource_budget import format_limit, settings
from .review_worktrees import list_review_worktrees
from .role_delivery import bind_role_delivery
from .scratch_worktrees import list_scratch_worktrees
from .turn_usage import turn_usage_callback
from .write_set_routes import load_write_grants

# The intentional differences, and the only ones; everything else is identical:
#  - api_token: a fresh spawn reuses its token, a resume rotates it (the old process is gone).
#  - connection hint: only a resumed process needs its connection instructions re-delivered once;
#    a fresh one gets them in its briefing.
#  - fresh_checkpoint: the hand-off note a fresh instance starts from; a resume carries its own
#    full context, so it is empty there.


def wire_attachment(att, runtime, hook_url, *, checkpoint="", resume=False):
    """Fill ``att`` with every hook and setting an adapter reads; blocking, run it in a thread."""
    conv = runtime.db.get_conversation(att["conv_id"])
    att["api_token"] = (rotate_api_token if resume else ensure_api_token)(runtime.db, att["id"])
    att["memory_limit"] = att.get("memory_limit") or format_limit(
        settings(runtime.db)["default_process_memory_bytes"]
    )
    att["global_prose"] = runtime.db.get_setting("global_prose")
    att["conv_name"], att["topic"] = conv["name"], conv["topic"]
    att["hook_url"] = hook_url(att["id"], att["runtime_owner"])
    load_write_grants(runtime.db, att)
    att["review_worktrees"] = list_review_worktrees(runtime.db, att["conv_id"])
    att["scratch_worktrees"] = list_scratch_worktrees(runtime.db, att["conv_id"])
    fence_workspaces.load(runtime.db, att)
    att["db_paths"] = database_paths(runtime.db)
    provision_connection(runtime.db.path, att)
    att["digest_rider"] = lambda: ""  # role delivery layers the goal and staffing on top
    if resume:
        bind_connection_hint(att)
    bind_role_delivery(runtime.db, att, runtime)
    att["fresh_checkpoint"] = "" if resume else checkpoint
    att["startup_attention"] = lambda prompt: surface_attention(runtime, att, prompt)
    att["on_process_exit"] = exit_callback(runtime, att)
    att["on_provider_error"] = provider_error_callback(runtime, att)
    att["on_turn_usage"] = turn_usage_callback(runtime, att)  # a no-op for adapters that never call it
    # The preset's explicit auto-compact threshold (§2.13), re-read on every
    # start so a resume picks up a changed preset; 0 lets the CLI default.
    att["auto_compact_tokens"] = auto_compact_tokens_for(runtime.db, att)
    if compaction_detect(att) == "transcript":
        # Claude gets its rebrief from hook stdout; a transcript-only
        # harness gets it as a private wake, and the adapter calls this
        # when its own tail sees the compaction (2.13, §5-generalised).
        att["on_compaction"] = transcript_compaction_callback(runtime, att)
