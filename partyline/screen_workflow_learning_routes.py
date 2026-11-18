"""Person controls and learner draft persistence for screen demonstrations."""

import asyncio
import json
import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from .auth_guard import request_principal
from .machine_scope import deny_unless, is_human
from .screen_workflow_bundle import load_bundle
from .screen_workflow_learning import (
    history_evidence,
    narrate,
    read_row,
    start as start_demonstration,
    stop as stop_demonstration,
)
from .screen_workflow_parameters import Strict
from .screen_workflow_evidence import authorized_window


class DemonstrationStart(Strict):
    window: str = Field(min_length=1, max_length=128)


class Narration(Strict):
    text: str = Field(min_length=1, max_length=2000)
    at: float | None = Field(default=None, ge=0)


class Draft(Strict):
    demonstration_id: str = Field(min_length=1, max_length=64)
    workflow: str = Field(min_length=1, max_length=80)
    alignment: dict[str, int] = Field(default_factory=dict, max_length=128)


class Preview(Strict):
    draft_id: str = Field(min_length=1, max_length=64)
    window: str = Field(min_length=1, max_length=128)
    parameters: dict = Field(default_factory=dict, max_length=32)


class History(Strict):
    window: str = Field(min_length=1, max_length=128)
    start: float = Field(ge=0)
    end: float = Field(gt=0)


def learning_router(service):
    db = service.db
    router = APIRouter(prefix="/api/conversations/{conv_id}/screen-workflows")

    def authorized(request, conv_id, capability="read"):
        principal = request_principal(request)
        deny_unless(db, principal, conv_id, capability)
        return principal

    def visible(principal, conv_id, demo_id):
        item = read_row(db, demo_id)
        row = db._exec("SELECT owner_id,grant_owner_id,grant_line_id "
                       "FROM screen_workflow_demonstrations WHERE id=?",
                       (demo_id,)).fetchone()
        if item["line"] != conv_id:
            raise HTTPException(404, "demonstration not found")
        if principal.kind == "user":
            can_see_screen = principal.user_id == row["grant_owner_id"]
        else:
            from .screen_grants import window_line_ids

            can_see_screen = row["grant_line_id"] in window_line_ids(db, principal.conv_id)
        if not can_see_screen:
            raise HTTPException(404, "demonstration not found")
        return item

    def owned(principal, conv_id, demo_id):
        item = visible(principal, conv_id, demo_id)
        row = db._exec("SELECT owner_id FROM screen_workflow_demonstrations WHERE id=?",
                       (demo_id,)).fetchone()
        if row["owner_id"] != principal.user_id:
            raise HTTPException(404, "demonstration not found")
        return item

    @router.post("/demonstrations")
    async def start_demo(conv_id: str, body: DemonstrationStart, request: Request):
        principal = authorized(request, conv_id, "write")
        deny_unless(db, principal, conv_id, "read")
        if not is_human(principal):
            raise HTTPException(403, "only a person can start a demonstration")
        grant, _ = authorized_window(service.hub, principal, body.window, conv_id)
        return read_row(db, start_demonstration(
            db, conv_id, grant["id"], principal.user_id, grant["owner_id"], grant["conv_id"]))

    @router.get("/learning")
    async def learning_review(conv_id: str, request: Request):
        authorized(request, conv_id)
        now = time.time()
        db._exec("DELETE FROM screen_workflow_demonstrations WHERE expires_at<=?", (now,))
        demos = db._exec("SELECT id,grant_owner_id,grant_line_id,started_at,stopped_at,state,calls,narration "
                         "FROM "
                         "screen_workflow_demonstrations WHERE conv_id=? ORDER BY started_at DESC LIMIT 20",
                         (conv_id,)).fetchall()
        drafts = db._exec("SELECT id,demonstration_id,name,path,revision,alignment,latest_preview,created_at "
                          "FROM screen_workflow_drafts WHERE conv_id=? ORDER BY created_at DESC LIMIT 20",
                          (conv_id,)).fetchall()
        visible_demos = []
        principal = request_principal(request)
        for row in demos:
            if principal.kind == "user":
                can_see_screen = principal.user_id == row["grant_owner_id"]
            else:
                from .screen_grants import window_line_ids

                can_see_screen = row["grant_line_id"] in window_line_ids(db, principal.conv_id)
            if can_see_screen:
                visible_demos.append({**dict(row), "calls": json.loads(row["calls"]),
                                      "narration": json.loads(row["narration"])})
        visible_ids = {item["id"] for item in visible_demos}
        visible_drafts = []
        for source in drafts:
            if source["demonstration_id"] not in visible_ids:
                continue
            item = dict(source)
            item["alignment"] = json.loads(item["alignment"])
            try:
                current = await service.revision(conv_id, item["name"])
                item["bundle"] = current.review()
                item["current"] = current.digest == item["revision"]
                from .screen_workflow_audit import approval

                item["approved"] = bool(approval(db, current)) if item["current"] else False
            except HTTPException:
                item["bundle"] = None
                item["current"] = False
                item["approved"] = False
            if not item["current"]:
                item["latest_preview"] = None
            elif item["latest_preview"]:
                item["latest_preview"] = json.loads(item["latest_preview"])
            visible_drafts.append(item)
        return {"demonstrations": visible_demos,
                "drafts": visible_drafts}

    @router.post("/demonstrations/from-history")
    async def history_demo(conv_id: str, body: History, request: Request):
        principal = authorized(request, conv_id, "read")
        if body.end <= body.start or body.end - body.start > 30 * 86400:
            raise HTTPException(422, "history interval must be ordered and no longer than 30 days")
        grant, _ = authorized_window(service.hub, principal, body.window, conv_id)
        calls, narration = history_evidence(
            db, conv_id, body.start, body.end, grant["id"], grant.get("title"))
        now = time.time()
        ident = str(uuid.uuid4())
        db._exec("INSERT INTO screen_workflow_demonstrations("
                 "id,conv_id,grant_id,owner_id,grant_owner_id,grant_line_id,"
                 "started_at,stopped_at,expires_at,state,calls,narration) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                 (ident, conv_id, grant["id"], principal.user_id or grant["owner_id"], grant["owner_id"],
                  grant["conv_id"],
                  body.start, now, now + 30 * 86400, "stopped_with_gaps",
                  json.dumps(calls, separators=(",", ":")),
                  json.dumps(narration, separators=(",", ":"))))
        return read_row(db, ident)

    @router.post("/demonstrations/{demo_id}/stop")
    async def stop_demo(conv_id: str, demo_id: str, request: Request):
        principal = authorized(request, conv_id, "write")
        deny_unless(db, principal, conv_id, "read")
        if not is_human(principal):
            raise HTTPException(403, "only a person can stop a demonstration")
        owned(principal, conv_id, demo_id)
        return stop_demonstration(db, demo_id)

    @router.get("/demonstrations/{demo_id}")
    async def show_demo(conv_id: str, demo_id: str, request: Request):
        authorized(request, conv_id)
        return visible(request_principal(request), conv_id, demo_id)

    @router.post("/demonstrations/{demo_id}/narration")
    async def demo_narration(conv_id: str, demo_id: str, body: Narration, request: Request):
        principal = authorized(request, conv_id, "write")
        deny_unless(db, principal, conv_id, "read")
        if not is_human(principal):
            raise HTTPException(403, "only a person can narrate a demonstration")
        owned(principal, conv_id, demo_id)
        narrate(db, demo_id, principal.user_id, body.text, body.at)
        return read_row(db, demo_id)

    @router.post("/drafts")
    async def save_draft(conv_id: str, body: Draft, request: Request):
        principal = authorized(request, conv_id, "write")
        deny_unless(db, principal, conv_id, "read")
        demonstration = visible(principal, conv_id, body.demonstration_id)
        if demonstration["line"] != conv_id or demonstration["state"] not in (
            "stopped", "stopped_with_gaps", "limit_reached"
        ):
            raise HTTPException(404, "stopped demonstration not found")
        try:
            from .screen_workflow_format import workflow_name
            name = workflow_name(body.workflow)
        except ValueError as exc:
            raise HTTPException(422, "invalid workflow name") from exc
        space = await service.checkout(conv_id)
        try:
            revision = await asyncio.to_thread(load_bundle, space, name)
        except HTTPException as exc:
            raise HTTPException(422, "write the complete workflow bundle in the line checkout first") from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(422, "invalid workflow bundle") from exc
        narration_indices = {line["index"] for line in demonstration["narration"]}
        root_ids = {getattr(entry, "id", f"repeat[{index + 1}]")
                    for index, entry in enumerate(revision.workflow.steps)}
        if set(body.alignment) - root_ids or set(body.alignment.values()) - narration_indices:
            raise HTTPException(422, "alignment must map workflow step IDs to narration lines")
        revision_digest = revision.digest
        draft_id = str(uuid.uuid4())
        db._exec(
            "INSERT INTO screen_workflow_drafts("
            "id,conv_id,demonstration_id,name,path,revision,alignment,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (draft_id, conv_id, body.demonstration_id, name, revision.path,
             revision_digest, json.dumps(body.alignment, separators=(",", ":")), time.time()),
        )
        return {"id": draft_id, "name": name, "revision": revision_digest, "approved": False,
                "bundle": revision.review(),
                "demonstration_id": body.demonstration_id}

    @router.post("/preview")
    async def preview(conv_id: str, body: Preview, request: Request):
        principal = authorized(request, conv_id, "read")
        draft = db._exec("SELECT demonstration_id,name,revision FROM screen_workflow_drafts "
                         "WHERE id=? AND conv_id=?",
                         (body.draft_id, conv_id)).fetchone()
        if draft is None:
            raise HTTPException(404, "workflow draft not found")
        visible(principal, conv_id, draft["demonstration_id"])
        grant, _ = authorized_window(service.hub, principal, body.window, conv_id)
        revision = await service.revision(conv_id, draft["name"])
        if revision.digest != draft["revision"]:
            raise HTTPException(409, "workflow draft changed; validate it again before preview")
        try:
            plan = revision.plan(body.parameters)
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, "invalid held-out parameters: " + str(exc)) from exc
        from .screen_workflow_preview import inspect_plan, observe
        tree = await observe(service, principal, conv_id, grant["id"])
        result = {"draft_id": body.draft_id, "revision": revision.digest,
                  "read_only": True, "steps": inspect_plan(tree, plan)}
        db._exec("UPDATE screen_workflow_drafts SET latest_preview=? WHERE id=?",
                 (json.dumps(result, separators=(",", ":")), body.draft_id))
        return result

    return router
