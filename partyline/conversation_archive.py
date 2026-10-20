"""Retirement: DELETE /api/conversations/{id} — every blocker in one answer.

Split out of ``conversation_routes`` (which sits at the 300-line cap) when
finding 2.8 of the «3d game» report added ``?clear_goal=true``: the flag
waives the ``goal_not_cleared`` blocker and clears the goal itself only once
every other blocker has come back empty, so a refused retirement never wipes
the goal of a line that is not finished.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .auth_guard import request_principal
from .conversation_contracts import BlockedArchiveResponse
from .contracts import ArchiveResponse, ConversationEvent, ConversationsChangedEvent
from .goal import set_goal
from .hierarchy import descendants
from .line_process_routes import detach_attachment, live_attachments, mid_turn_blocker
from .line_subtree import archive_line, archive_subtree
from .machine_scope import deny_unless, is_human
from .retirement import archive_blockers
from .review_worktrees import prune_review_worktrees
from .scratch_worktrees import prune_scratch_worktrees
from .attachment_tmp import reap_line_tmp
from .legacy_tmp import reap_legacy_temp
from .system_notice import post_system_notice
from .worktree_lifecycle import archive_worktree_if_safe, discard_worktree
from .retirement_preview import preview
from .retirement_contracts import RetirementAudit, RetirementPreview
from .retirement_force import admission, retire


def _server():
    from . import server
    return server


def register_archive_route(app: FastAPI, presence):
    """Mount DELETE /api/conversations/{id}; return the handler for server re-export."""

    @app.get("/api/conversations/{conv_id}/retirement-preview", response_model=RetirementPreview)
    async def retirement_preview(request: Request, conv_id: str, include_children: bool = False):
        runtime = _server().runtime
        return await asyncio.to_thread(
            preview, runtime.db, request_principal(request), conv_id, include_children,
            getattr(runtime, "presence", None) or presence)

    @app.get("/api/conversations/{conv_id}/retirement-audit", response_model=list[RetirementAudit])
    def retirement_audit(request: Request, conv_id: str):
        db = _server().runtime.db
        deny_unless(db, request_principal(request), conv_id, "read")
        rows = db._exec(
            "SELECT * FROM retirement_audit WHERE target=? ORDER BY created_at DESC LIMIT 20",
            (conv_id,)).fetchall()
        return [{**dict(row), **{key: json.loads(row[key]) for key in
                                ("principal", "evidence", "recovery")}} for row in rows]

    @app.delete(
        "/api/conversations/{conv_id}",
        response_model=ArchiveResponse,
        responses={409: {"model": BlockedArchiveResponse}},
    )
    async def archive_conversation(
        request: Request, conv_id: str, include_children: bool = False, discard: bool = False,
        stop_processes: bool = False, clear_goal: bool = False,
        force_discard: bool = False, preview_token: str | None = None,
    ):
        runtime = _server().runtime
        db = runtime.db
        principal = request_principal(request)
        deny_unless(db, principal, conv_id, "archive")
        from .orchestrator_store import task_not_retirable_by
        if not is_human(principal) and task_not_retirable_by(db, principal, conv_id, include_children):
            raise HTTPException(403, "only a person or the task's root captain may archive task lines")
        if conv_id in getattr(db, "retiring_lines", set()):
            raise HTTPException(409, "retirement is already in progress")
        conv = db.get_conversation(conv_id)
        if conv["archived_at"]:
            raise HTTPException(409, "line is already archived")
        if force_discard:
            with admission(db, conv_id, include_children):
                return await retire(runtime, principal, conv_id, include_children=include_children,
                                    stop_processes=stop_processes, clear_goal=clear_goal,
                                    preview_token=preview_token,
                                    presence=getattr(runtime, "presence", None) or presence)
        pre_stopped: list[str] = []
        live: list[dict] = []
        if stop_processes:
            live = live_attachments(db, conv_id, include_children)
            working_presence = getattr(runtime, "presence", None) or presence
        # Every blocker in one answer, so a captain fixes them in one pass
        # instead of learning the next one on each round trip.
        blockers = await asyncio.to_thread(
            archive_blockers, db, conv_id,
            include_children=include_children, discard=discard,
            strict=not is_human(principal), ignore_live_processes=stop_processes,
        )
        if clear_goal:
            # The goal blocker is what this flag waives — and only that one.
            # The goal itself survives a refusal: a line refused for another
            # reason is not finished, and its goal nudges must keep firing.
            blockers = [b for b in blockers if b["code"] != "goal_not_cleared"]
        if stop_processes and (blocker := mid_turn_blocker(live, working_presence)):
            blockers.append(blocker)
        if blockers:
            summary = "; ".join(blocker["message"] for blocker in blockers)
            return JSONResponse(
                status_code=409, content={"detail": summary, "blockers": blockers}
            )
        clear_ids = ([conv_id, *descendants(db, conv_id, include_archived=False)]
                     if include_children else [conv_id])
        for goal_id in clear_ids if clear_goal else []:
            if not db.get_conversation(goal_id).get("goal"):
                continue
            set_goal(db, goal_id, "")
            await post_system_notice(
                runtime, goal_id, f"☏ goal cleared by @{principal.name} (retirement)",
                actor=principal,
            )
            await runtime.broadcast(
                goal_id, ConversationEvent(conversation=db.get_conversation(goal_id)))
        for attachment in live:
            await detach_attachment(runtime, attachment["id"])
            pre_stopped.append(attachment["name"])
        if include_children:
            stopped, archived = await archive_subtree(runtime, conv_id)
        else:
            stopped, archived = await archive_line(runtime, conv_id), [conv_id]
        stopped = [*pre_stopped, *stopped]
        removed, kept_reason = False, None
        for line_id in archived:
            if discard:
                # The explicit discard: a merged branch's dirty worktree goes.
                line_removed = await asyncio.to_thread(discard_worktree, db, line_id)
                reason = None
            else:
                line_removed, reason = await asyncio.to_thread(
                    archive_worktree_if_safe, db, line_id)
            await asyncio.to_thread(prune_review_worktrees, db, line_id)
            await asyncio.to_thread(prune_scratch_worktrees, db, line_id)
            await asyncio.to_thread(reap_line_tmp, db, line_id)
            if line_id == conv_id:
                removed, kept_reason = line_removed, reason
        # One walk of the legacy locations for the whole archive, after the
        # per-line loop — not one walk per archived line.
        await asyncio.to_thread(reap_legacy_temp, db)
        await runtime.broadcast_all(ConversationsChangedEvent())
        return {"ok": True, "archived": True, "stopped": stopped,
                "archived_ids": archived, "worktree_removed": removed,
                "worktree_kept_reason": kept_reason,
                "conversation": db.get_conversation(conv_id)}

    return archive_conversation
