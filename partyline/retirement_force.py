"""Explicit root retirement: recover first, check again, retire leaves first."""

import asyncio
import hmac
import json
import os
import time
import uuid
from contextlib import contextmanager

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from .contracts import ConversationsChangedEvent
from .attachment_tmp import reap_line_tmp
from .legacy_tmp import reap_legacy_temp
from .goal import set_goal
from .hierarchy import descendants
from .line_process_routes import detach_attachment, live_attachments
from .line_subtree import archive_line
from .nested_repositories import keep_reason
from .retirement_git import git, snapshot
from .task_teardown import teardown
from .retirement_preview import force_authorized, identity, plan, token
from .retirement_auxiliary import auxiliary_heads, cleanup_auxiliary, recover_auxiliary
from .system_notice import post_system_notice


@contextmanager
def admission(db, target, include_children):
    """Refuse new Partyline mutations while a forced plan is being executed."""
    ids = {target, *(descendants(db, target) if include_children else [])}
    active = getattr(db, "retiring_lines", set())
    if active & ids:
        raise HTTPException(409, "retirement is already in progress")
    db.retiring_lines = active | ids
    try:
        yield
    finally:
        db.retiring_lines -= ids


def _audit(db, audit_id, principal, target, decision, evidence, recovery, error=None):
    db._exec(
        "INSERT OR REPLACE INTO retirement_audit "
        "(id,principal,target,decision,evidence,recovery,error,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (audit_id, json.dumps(identity(principal)), target, decision, json.dumps(evidence),
         json.dumps(recovery), error, time.time()),
    )


def _remove(state):
    """Remove only the managed worktree and its owned, unchanged host ref."""
    if not state:
        return False
    if keep_reason(state["cwd"]):
        return False  # a nested repository: kept with its branch, named in the result
    git(state["root"], "worktree", "remove", "--force", state["cwd"])
    if os.path.exists(state["cwd"]):
        raise HTTPException(409, "worktree removal did not complete")
    if state["branch_tip"]:
        git(state["root"], "update-ref", "-d", f"refs/heads/{state['branch']}", state["branch_tip"])
    return True


def _checked_remove(db, principal, target, line, presence, audit_id):
    force_authorized(db, principal, target)
    current = plan(db, principal, line["id"], False, presence,
                   f"refs/partyline/discarded/{audit_id}/")["lines"][0]
    if (current["auxiliary_worktrees_preserved"] != line["auxiliary_worktrees_preserved"]
            or current["auxiliary_worktrees_pruned"] != line["auxiliary_worktrees_pruned"]
            or auxiliary_heads(current["auxiliary_worktrees"]) != auxiliary_heads(
                line["auxiliary_worktrees"])):
        raise HTTPException(409, "auxiliary worktree state changed; refresh retirement preview")
    if current["git"] != line["git"] or current["goal"] != line["goal"] \
            or current["parent_id"] != line["parent_id"]:
        raise HTTPException(409, "retirement changed after process stop; refresh preview")
    if current["children"] or live_attachments(db, line["id"], False):
        raise HTTPException(409, "retirement gained a child or live process")
    teardown(db, line["id"], (db.get_conversation(line["id"]) or {}).get("cwd") or "")
    return _remove(current["git"])


async def retire(runtime, principal, target, *, include_children, stop_processes,
                 clear_goal, preview_token, presence):
    db = runtime.db
    force_authorized(db, principal, target)
    if not preview_token:
        raise HTTPException(409, "force_discard requires a retirement preview_token")
    # Serialize force executions within this server. Other lifecycle operations
    # are detected by the repeated state checks, including generation changes.
    if not hasattr(runtime, "retirement_lock"):
        runtime.retirement_lock = asyncio.Lock()
    async with runtime.retirement_lock:
        evidence = await asyncio.to_thread(plan, db, principal, target, include_children, presence)
        if not hmac.compare_digest(preview_token, token(db, evidence)):
            raise HTTPException(409, "retirement preview is stale or belongs to another principal")
        for line in evidence["lines"]:
            if line["goal"] and not clear_goal:
                raise HTTPException(409, "clear_goal=true is required for an uncleared goal")
            if line["children"] and not include_children:
                raise HTTPException(409, "include_children=true is required for child lines")
            if any(att["status"] in ("starting", "running") for att in line["attachments"]) \
                    and not stop_processes:
                raise HTTPException(409, "stop_processes=true is required for live processes")
        audit_id = uuid.uuid4().hex
        recovery, completed, stopped, preserved_paths, kept = {}, [], [], [], []
        decision = {"force_discard": True, "include_children": include_children,
                    "clear_goal": clear_goal, "stop_processes": stop_processes,
                    "preview_token": preview_token, "plan": evidence}
        _audit(db, audit_id, principal, target, "attempted", decision, recovery)
        try:
            # Every snapshot succeeds before any process or line is retired.
            for line in evidence["lines"]:
                recovery[line["id"]] = {}
                if line["git"]:
                    recovery[line["id"]] = await asyncio.to_thread(
                        snapshot, line["git"], audit_id + "/" + line["id"])
                recovery[line["id"]].update(await asyncio.to_thread(
                    recover_auxiliary, line, audit_id + "/" + line["id"]))
                _audit(db, audit_id, principal, target, "snapshotted", decision, recovery)
            fresh = await asyncio.to_thread(plan, db, principal, target, include_children, presence,
                                            f"refs/partyline/discarded/{audit_id}/")
            if evidence != fresh:
                raise HTTPException(409, "retirement changed during snapshot; refresh preview")
            force_authorized(db, principal, target)
            for line in evidence["lines"]:
                line_id = line["id"]
                for att in live_attachments(db, line_id, False):
                    await detach_attachment(runtime, att["id"])
                    stopped.append(att["name"])
                force_authorized(db, principal, target)
                conv = db.get_conversation(line_id)
                removed = await asyncio.to_thread(
                    _checked_remove, db, principal, target, line, presence, audit_id)
                if not removed and (reason := keep_reason(conv.get("cwd") or "")):
                    kept.append(reason)
                preserved_paths.extend(await asyncio.to_thread(cleanup_auxiliary, db, line, audit_id))
                await asyncio.to_thread(reap_line_tmp, db, line_id)
                if clear_goal and conv.get("goal"):
                    set_goal(db, line_id, "")
                await archive_line(runtime, line_id)
                completed.append(line_id)
                _audit(db, audit_id, principal, target, "in_progress",
                       {**decision, "completed": completed}, recovery)
        except Exception as exc:
            detail = (exc.detail if isinstance(exc, HTTPException)
                      else "retirement failed; remaining lines retained")
            preserved_paths = [row["path"] for row in db._exec(
                "SELECT path FROM retirement_preserved_paths WHERE audit_id=? ORDER BY path",
                (audit_id,)).fetchall()]
            _audit(db, audit_id, principal, target, "failed",
                   {**decision, "completed": completed}, recovery, str(detail))
            await runtime.broadcast_all(ConversationsChangedEvent())
            return JSONResponse(status_code=409, content={"detail": detail, "audit_id": audit_id,
                "archived_ids": completed, "pending_ids": [line["id"] for line in evidence["lines"]
                                                          if line["id"] not in completed],
                "recovery_refs": recovery, "preserved_paths": preserved_paths})
        await asyncio.to_thread(reap_legacy_temp, db)
        _audit(db, audit_id, principal, target, "completed", decision, recovery)
        notice_line = principal.conv_id or target
        await post_system_notice(runtime, notice_line,
            f"☏ forced retirement by {principal.name}: {target}; audit {audit_id}; "
            f"recovery refs recorded, {len(preserved_paths)} dirty auxiliary paths retained; "
            "clean auxiliary worktrees and temporary directories removed", actor=principal)
        await runtime.broadcast_all(ConversationsChangedEvent())
        return {"ok": True, "archived": True, "stopped": stopped, "archived_ids": completed,
                "worktree_removed": removed, "worktree_kept_reason": "; ".join(kept) or None,
                "audit_id": audit_id, "recovery_refs": recovery, "preserved_paths": preserved_paths,
                "conversation": db.get_conversation(target)}
