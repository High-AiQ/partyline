"""HTTP: appoint leads, create children, parent-pulled reports, machine messages."""

from __future__ import annotations

import asyncio


from fastapi import APIRouter, HTTPException, Query, Request

from .auth_guard import request_principal
from .contracts import (
    ConversationEvent,
    ConversationResponse,
    ConversationsChangedEvent,
)
from .orchestrator_store import write_captain_style
from .mention_relay import live_manager, post_private, ring_workers
from .message_routing import post_identified
from .hierarchy import (
    HierarchyError,
    child_ids,
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
    ParentIn,
    Report,
    ReportIn,
)
from .accept_sha import accepted_note
from . import checkout_health
from .line_worktree import line_cwd
from .machine_scope import capability_state, deny_unless
from .reports import (
    ReportError,
    acknowledge,
    add as add_report,
    DEFAULT_LIMIT,
    MAX_LIMIT,
    get_for_parent,
    list_for_parent,
    mark_notified,
    release_wake_claim,
    wake_message,
)
from .system_notice import post_system_notice


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
        return {"briefing": _instructions(state, db)}

    @router.get("/api/conversations/{conv_id}/lead", response_model=LeadOut)
    def get_lead(request: Request, conv_id: str):
        deny_unless(db, request_principal(request), conv_id, "read")
        lead = lead_attachment(db, conv_id)
        return LeadOut(attachment_id=None if lead is None else lead["id"])

    @router.post("/api/conversations/{conv_id}/lead", response_model=LeadOut)
    async def appoint_lead(request: Request, conv_id: str, body: LeadIn):
        principal = request_principal(request)
        deny_unless(db, principal, conv_id, "appoint_lead")
        before = lead_attachment(db, conv_id)
        prior = db.get_conversation(conv_id)
        restyled = False
        if body.captain_mode is not None:
            # Before the captain is marked lead and briefed, so its first pack matches.
            write_captain_style(db, principal, conv_id, body.captain_mode,
                                body.default_review_policy or prior["default_review_policy"])
            restyled = (body.captain_mode, body.default_review_policy or prior["default_review_policy"]) != (
                prior["captain_mode"], prior["default_review_policy"])
            if restyled:
                updated = db.get_conversation(conv_id)
                await runtime.broadcast(conv_id, ConversationEvent(conversation=updated))
                await runtime.broadcast_all(ConversationsChangedEvent())
        if not restyled and (before["id"] if before else None) == body.attachment_id:
            return LeadOut(attachment_id=body.attachment_id)  # already so: no second ring
        try:
            set_lead(db, conv_id, body.attachment_id)
        except HierarchyError as exc:
            if restyled:
                db._exec("UPDATE conversations SET captain_mode=?,default_review_policy=? WHERE id=?",
                         (prior["captain_mode"], prior["default_review_policy"], conv_id))
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
                actor=principal,
            )
        if live(att):
            # Everyone hears where the line stands before the captain plans from it.
            health = await asyncio.to_thread(checkout_health.inspect, line_cwd(db, conv_id))
            if text := (checkout_health.describe(health) or "") + accepted_note(db, conv_id):
                await post_system_notice(runtime, conv_id, text, actor=principal)
            await post_private(
                runtime, conv_id, "system", "system",
                f"☏ @{att['name']} is now this line's captain — the captain pack rides this "
                "wake; read it before acting further",
                audience=att["id"],
                actor=principal,
            )
            await ring_workers(runtime, conv_id, att)  # workers learn their pack now, not later
        return LeadOut(attachment_id=body.attachment_id)

    @router.put("/api/conversations/{conv_id}/parent", response_model=ConversationResponse)
    async def link_parent(request: Request, conv_id: str, body: ParentIn):
        deny_unless(db, request_principal(request), conv_id, "link_parent")
        from .orchestrator_store import task
        current = db.get_conversation(conv_id)
        if task(db, conv_id) or (body.parent_id and current.get('captain_mode') == 'orchestrator'):
            raise HTTPException(409, 'task parents and orchestrator root placement cannot change')
        if (body.parent_id and
                (db.get_conversation(body.parent_id) or {}).get('captain_mode') == 'orchestrator'):
            raise HTTPException(409, 'orchestrator children are created through create_task')
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
        from .child_create import create_child as create
        if (db.get_conversation(conv_id) or {}).get("captain_mode") == "orchestrator":
            raise HTTPException(409, "use create_task for an orchestrator root")
        return await create(runtime, request_principal(request), conv_id, body)

    @router.get(
        "/api/conversations/{conv_id}/children",
        response_model=list[ConversationResponse],
    )
    def list_children(request: Request, conv_id: str):
        deny_unless(db, request_principal(request), conv_id, "read")
        return [db.get_conversation(cid) for cid in child_ids(db, conv_id)]

    @router.get("/api/conversations/{conv_id}/reports", response_model=list[Report])
    def list_reports(
        request: Request,
        conv_id: str,
        limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
        after_id: int | None = Query(None, ge=0),
        before_id: int | None = Query(None, ge=0),
    ):
        deny_unless(db, request_principal(request), conv_id, "read_reports")
        if after_id is not None and before_id is not None:
            raise HTTPException(400, "after_id and before_id are exclusive")
        rows = list_for_parent(db, conv_id, limit, after_id, before_id)
        return [_report_model(row) for row in rows]

    @router.get("/api/conversations/{conv_id}/reports/{report_id}", response_model=Report)
    def read_report(request: Request, conv_id: str, report_id: int):
        deny_unless(db, request_principal(request), conv_id, "read_reports")
        try:
            return _report_model(get_for_parent(db, conv_id, report_id))
        except ReportError as exc:
            raise _http(exc) from exc

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

    return router
