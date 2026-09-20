"""HTTP: appoint leads, create children, parent-pulled reports, machine messages."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, HTTPException, Query, Request

from .auth_guard import request_principal
from .contracts import (
    ConversationResponse,
    MessageResponse,
    ConversationsChangedEvent,
)
from .mention_relay import live_manager, post_private, ring_workers
from .message_routing import post_identified
from .hierarchy import (
    HierarchyError,
    child_ids,
    create_child_conversation,
    lead_attachment,
    parent_id_of,
    set_lead,
    set_parent,
)
from .hierarchy_contracts import (
    AckIn,
    CapabilityState,
    ChildCreatedResponse,
    ChildIn,
    LeadIn,
    LeadOut,
    MessageIn,
    ParentIn,
    Report,
    ReportIn,
)
from . import checkout_health
from .accept_sha import accepted_note
from .line_worktree import describe, line_cwd, place_child, placement_root
from .machine_scope import capability_state, deny_staffed_split, deny_unless, is_human
from .reports import (
    ReportError,
    acknowledge,
    add as add_report,
    list_for_parent,
    mark_notified,
    release_wake_claim,
    wake_message,
)


def _http(exc: HierarchyError | ReportError) -> HTTPException:
    return HTTPException(exc.status_code, exc.detail)


def _report_model(row: dict) -> dict:
    return {**row, "notify": bool(row.get("notify")), "revision": int(row.get("revision") or 1)}


def hierarchy_router(runtime) -> APIRouter:
    router = APIRouter()
    db = runtime.db

    @router.get("/api/capabilities", response_model=CapabilityState)
    def get_capabilities(request: Request, conv_id: str | None = Query(default=None)):
        return capability_state(db, request_principal(request), conv_id)

    @router.get("/api/conversations/{conv_id}/briefing")
    def get_briefing(request: Request, conv_id: str):
        principal = request_principal(request)
        deny_unless(db, principal, conv_id, "read")
        if principal.kind != "machine" or principal.conv_id != conv_id:
            raise HTTPException(403, "the captain pack is attachment-specific")
        from .role_delivery import _instructions, current_role

        state = current_role(db, principal.attachment_id)
        if state.role != "lead":
            raise HTTPException(403, "the captain pack is only available to captains")
        return {"briefing": _instructions(state)}

    @router.get("/api/conversations/{conv_id}/lead", response_model=LeadOut)
    def get_lead(request: Request, conv_id: str):
        deny_unless(db, request_principal(request), conv_id, "read")
        lead = lead_attachment(db, conv_id)
        return LeadOut(attachment_id=None if lead is None else lead["id"])

    @router.post("/api/conversations/{conv_id}/lead", response_model=LeadOut)
    async def appoint_lead(request: Request, conv_id: str, body: LeadIn):
        deny_unless(db, request_principal(request), conv_id, "appoint_lead")
        before = lead_attachment(db, conv_id)
        if (before["id"] if before else None) == body.attachment_id:
            return LeadOut(attachment_id=body.attachment_id)  # already so: no second ring
        try:
            set_lead(db, conv_id, body.attachment_id)
        except HierarchyError as exc:
            raise _http(exc) from exc
        att = db.get_attachment(body.attachment_id) if body.attachment_id else None

        def live(row):
            return row is not None and row["status"] == "running" and row["id"] in runtime.live

        # Ring both sides now rather than on their next wake: a process that appoints
        # itself mid-turn otherwise keeps acting on the ordinary briefing; a replaced
        # captain otherwise keeps acting as captain until something else wakes it. The
        # digest rider carries the pack, or the "ordinary participant" correction.
        if live(before) and before["id"] != (att["id"] if att else None):
            successor = f"@{att['name']} is" if att else "nobody is"
            await post_private(
                runtime, conv_id, "system", "system",
                f"☏ @{before['name']} is no longer this line's captain — {successor} now. Stop "
                "assigning, appointing, and crossing lines; finish as an ordinary participant",
                audience=before["id"],
            )
        if live(att):
            # Everyone hears where the line stands before the captain plans from it.
            health = await asyncio.to_thread(checkout_health.inspect, line_cwd(db, conv_id))
            if text := (checkout_health.describe(health) or "") + accepted_note(db, conv_id):
                await runtime.post_message(conv_id, "system", "system", text)
            await post_private(
                runtime, conv_id, "system", "system",
                f"☏ @{att['name']} is now this line's captain — the captain pack rides this "
                "wake; read it before acting further",
                audience=att["id"],
            )
            await ring_workers(runtime, conv_id, att)  # workers learn their pack now, not later
        return LeadOut(attachment_id=body.attachment_id)

    @router.put("/api/conversations/{conv_id}/parent", response_model=ConversationResponse)
    async def link_parent(request: Request, conv_id: str, body: ParentIn):
        deny_unless(db, request_principal(request), conv_id, "link_parent")
        try:
            conv = set_parent(db, conv_id, body.parent_id)
        except HierarchyError as exc:
            raise _http(exc) from exc
        await runtime.broadcast_all(ConversationsChangedEvent())
        return ConversationResponse.model_validate(conv)

    @router.post(
        "/api/conversations/{conv_id}/children",
        response_model=ChildCreatedResponse,
        status_code=201,
    )
    async def create_child(request: Request, conv_id: str, body: ChildIn):
        principal = request_principal(request)
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
            raise _http(exc) from exc
        placed = place_child(db, conv_id, conv["id"], base=base_ref, root=target)
        if (base_ref or target) and not placed.get("branch"):
            # A failed placement must not silently inherit the parent checkout — not
            # for an explicit upstream base, not for an explicit repository — so the
            # line is rolled back and the caller is told instead of left seated there.
            db.delete_conversation(conv["id"])
            raise HTTPException(
                409, f"the child worktree could not be created on {base_ref or target}")
        if where := describe(placed):
            await runtime.post_message(conv["id"], "system", "system", where)
        if placed.get("branch"):
            # The base notice describes the checkout the child actually starts from.
            if notice := checkout_health.describe(base_health):
                notice = notice.replace("☏ checkout:", "☏ base checkout:", 1)
                await runtime.post_message(conv["id"], "system", "system", notice)
        conv = db.get_conversation(conv["id"])
        goal, topic = body.goal.strip(), body.topic.strip()
        if goal or topic:
            # Born briefed: the goal rides the child manager's wakes, the topic
            # is standing context for everyone on the child line. Both are
            # announced there so the hand-off is on the record.
            db._exec("UPDATE conversations SET goal=?, topic=? WHERE id=?", (goal, topic, conv["id"]))
            conv = db.get_conversation(conv["id"])
            who = f"@{request_principal(request).name}"
            if topic:
                await runtime.post_message(conv["id"], "system", "system",
                                           f"☏ topic set by {who}: {topic}")
            if goal:
                await runtime.post_message(conv["id"], "system", "system",
                                           f"☏ goal set by {who}: {goal}")
        await runtime.broadcast_all(ConversationsChangedEvent())
        return ChildCreatedResponse(
            conversation=ConversationResponse.model_validate(conv)
        )

    @router.get(
        "/api/conversations/{conv_id}/children",
        response_model=list[ConversationResponse],
    )
    def list_children(request: Request, conv_id: str):
        deny_unless(db, request_principal(request), conv_id, "read")
        return [db.get_conversation(cid) for cid in child_ids(db, conv_id)]

    @router.get("/api/conversations/{conv_id}/reports", response_model=list[Report])
    def list_reports(request: Request, conv_id: str):
        deny_unless(db, request_principal(request), conv_id, "read_reports")
        return [_report_model(row) for row in list_for_parent(db, conv_id)]

    @router.post(
        "/api/conversations/{conv_id}/reports",
        response_model=Report,
        status_code=201,
    )
    async def post_report(request: Request, conv_id: str, body: ReportIn):
        principal = request_principal(request)
        deny_unless(db, principal, conv_id, "notify" if body.notify else "report")
        conv = db.get_conversation(conv_id)
        parent = parent_id_of(conv)
        if not parent:
            raise HTTPException(400, "this line has no parent to report to")
        try:
            row, should_wake = add_report(
                db,
                parent,
                conv_id,
                principal.name,
                body.body,
                author_attachment_id=principal.attachment_id,
                notify=body.notify,
            )
        except ReportError as exc:
            raise _http(exc) from exc
        # The claim this caller took. Every later write is fenced on it, so a
        # lease that expired mid-delivery cannot clear or complete the wake a
        # newer attempt now owns.
        claim = row.get("notifying_at")
        if should_wake:
            # The report is already stored. The wake is a separate fact, and
            # it is only recorded once it has actually been posted: with no
            # manager appointed, or if delivery raises, the row stays
            # undelivered so the next escalation from this child retries it
            # rather than coalescing into a silence nobody asked for.
            lead = live_manager(runtime, parent)
            if lead is None:
                row = release_wake_claim(db, row["id"], claim)
            else:
                try:
                    await post_identified(
                        runtime,
                        parent,
                        principal,
                        wake_message(lead["name"], row["id"]),
                    )
                except Exception:
                    # Hand the wake back before surfacing the failure: a claim
                    # kept by a delivery that did not happen is indistinguish-
                    # able from one that did, and mutes this child.
                    release_wake_claim(db, row["id"], claim)
                    raise
                row = mark_notified(db, row["id"], claim)
        return _report_model(row)

    @router.post(
        "/api/conversations/{conv_id}/reports/{report_id}/ack",
        response_model=Report,
    )
    def ack_report(request: Request, conv_id: str, report_id: int, body: AckIn):
        deny_unless(db, request_principal(request), conv_id, "read_reports")
        try:
            return _report_model(
                acknowledge(db, report_id, conv_id, body.revision)
            )
        except ReportError as exc:
            raise _http(exc) from exc

    @router.post(
        "/api/conversations/{conv_id}/messages",
        response_model=MessageResponse,
    )
    async def post_message(request: Request, conv_id: str, body: MessageIn):
        principal = request_principal(request)
        capability = (
            "write" if principal.conv_id == conv_id or is_human(principal) else "assign"
        )
        deny_unless(db, principal, conv_id, capability)
        return await post_identified(runtime, conv_id, principal, body.body)

    return router
