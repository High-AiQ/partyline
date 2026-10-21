"""Shared, authorized child creation for tree captains and orchestrators."""

import asyncio
import uuid

from fastapi import HTTPException

from . import checkout_health
from .contracts import ConversationResponse, ConversationsChangedEvent
from .hierarchy import HierarchyError, create_child_conversation
from .hierarchy_contracts import ChildCreatedResponse
from .line_worktree import describe, line_cwd, place_child, placement_root
from .machine_scope import deny_staffed_split, deny_unless, is_human
from .task_workspaces import describe as task_describe, place_task
from .system_notice import post_system_notice


async def create_child(runtime, principal, conv_id, body, workspace=False):
    db = runtime.db
    from .orchestrator_store import task
    if task(db, conv_id):
        raise HTTPException(409, "task lines cannot create child lines")
    deny_staffed_split(db, principal, conv_id)  # the loud reason first
    deny_unless(db, principal, conv_id, "create_child")
    cwd = line_cwd(db, conv_id)
    target, target_error = await asyncio.to_thread(placement_root, body.repository)
    if target_error:
        raise HTTPException(400, target_error)
    # The stale-base guard reads the parent's checkout, or the target's when placed there.
    base_health = await asyncio.to_thread(
        checkout_health.inspect, cwd if target is None else target)
    base_ref, base_error = await asyncio.to_thread(
        checkout_health.child_base_ref, target or cwd, body.base == "upstream",
        is_human(principal), base_health)
    if base_error:
        raise HTTPException(409, base_error)
    name = body.name.strip() or "untitled"
    try:
        conv = create_child_conversation(db, conv_id, str(uuid.uuid4()), name)
    except HierarchyError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    placed = await asyncio.to_thread(place_task, db, conv_id, conv["id"]) if workspace else None
    placed = placed or place_child(db, conv_id, conv["id"], base=base_ref, root=target)
    if (base_ref or target) and not placed.get("branch"):
        # A failed placement must not silently inherit the parent checkout — not
        # for an explicit upstream base, not for an explicit repository — so the
        # line is rolled back and the caller is told instead of left seated there.
        db.delete_conversation(conv["id"])
        raise HTTPException(
            409, f"the child worktree could not be created on {base_ref or target}")
    if where := (task_describe(placed) if placed.get("workspaces") else describe(placed)):
        await post_system_notice(runtime, conv["id"], where, actor=principal)
    if placed.get("branch"):
        # The base notice describes the checkout the child actually starts from.
        if notice := checkout_health.describe(base_health):
            notice = notice.replace("☏ checkout:", "☏ base checkout:", 1)
            await post_system_notice(runtime, conv["id"], notice, actor=principal)
    conv = db.get_conversation(conv["id"])
    goal, topic = body.goal.strip(), body.topic.strip()
    if goal or topic:
        # Born briefed: the goal rides the child manager's wakes, the topic
        # is standing context for everyone on the child line. Both are
        # announced there so the hand-off is on the record.
        db._exec("UPDATE conversations SET goal=?, topic=? WHERE id=?", (goal, topic, conv["id"]))
        conv = db.get_conversation(conv["id"])
        who = f"@{principal.name}"
        if topic:
            await post_system_notice(
                runtime, conv["id"], f"☏ topic set by {who}: {topic}", actor=principal)
        if goal:
            await post_system_notice(
                runtime, conv["id"], f"☏ goal set by {who}: {goal}", actor=principal)
    await runtime.broadcast_all(ConversationsChangedEvent())
    return ChildCreatedResponse(
        conversation=ConversationResponse.model_validate(conv)
    )
