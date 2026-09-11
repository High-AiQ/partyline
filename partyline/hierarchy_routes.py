"""HTTP: appoint leads, create children, parent-pulled reports, machine messages."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Request

from .auth_guard import request_principal
from .contracts import (
    ConversationResponse,
    ConversationsChangedEvent,
    MessageEvent,
    MessageResponse,
)
from .hierarchy import (
    HierarchyError,
    child_ids,
    create_child_conversation,
    lead_attachment,
    parent_id_of,
    set_lead,
    set_parent,
    stamp_source,
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
from .machine_scope import capability_state, deny_unless, is_human
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


def _live_manager(runtime, conv_id: str) -> dict | None:
    """The parent's manager, only if a message could actually reach it.

    The same three conditions `message_routing` uses, deliberately: status
    exactly ``running``, a live adapter, and an activation that still matches.
    A ``starting`` or superseded manager is not delivery — posting at one
    would mark the report notified while nobody was woken, which is the
    silence this whole path exists to avoid.
    """
    lead = lead_attachment(runtime.db, conv_id)
    if lead is None or lead["status"] != "running":
        return None
    adapter = runtime.live.get(lead["id"])
    if adapter is None or not runtime.activation_matches(adapter, lead):
        return None
    return lead


def _report_model(row: dict) -> dict:
    return {
        **row,
        "notify": bool(row.get("notify")),
        "revision": int(row.get("revision") or 1),
    }


async def _post_identified(runtime, conv_id, principal, body: str):
    kind = "agent" if principal.kind == "machine" else "human"
    stored = runtime.db.add_message(conv_id, principal.name, kind, body)
    stored = {**stored, **stamp_source(runtime.db, stored["id"], principal)}
    await runtime.broadcast(
        conv_id, MessageEvent(message=MessageResponse.model_validate(stored))
    )
    await runtime.route_mentions(conv_id, stored)
    return stored


def hierarchy_router(runtime) -> APIRouter:
    router = APIRouter()
    db = runtime.db

    @router.get("/api/capabilities", response_model=CapabilityState)
    def get_capabilities(request: Request, conv_id: str | None = Query(default=None)):
        return capability_state(db, request_principal(request), conv_id)

    @router.get("/api/conversations/{conv_id}/lead", response_model=LeadOut)
    def get_lead(request: Request, conv_id: str):
        deny_unless(db, request_principal(request), conv_id, "read")
        lead = lead_attachment(db, conv_id)
        return LeadOut(attachment_id=None if lead is None else lead["id"])

    @router.post("/api/conversations/{conv_id}/lead", response_model=LeadOut)
    def appoint_lead(request: Request, conv_id: str, body: LeadIn):
        deny_unless(db, request_principal(request), conv_id, "appoint_lead")
        try:
            set_lead(db, conv_id, body.attachment_id)
        except HierarchyError as exc:
            raise _http(exc) from exc
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
        deny_unless(db, request_principal(request), conv_id, "create_child")
        name = body.name.strip() or "untitled"
        try:
            conv = create_child_conversation(db, conv_id, str(uuid.uuid4()), name)
        except HierarchyError as exc:
            raise _http(exc) from exc
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
            lead = _live_manager(runtime, parent)
            if lead is None:
                row = release_wake_claim(db, row["id"], claim)
            else:
                try:
                    await _post_identified(
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
        return await _post_identified(runtime, conv_id, principal, body.body)

    return router
