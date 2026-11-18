"""Line-scoped workflow API. Approval, confirmation and audit require people."""

import asyncio
import os
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import Field, JsonValue, StringConstraints

from . import screen_workflow_audit as audit
from .auth_guard import request_principal
from .machine_scope import deny_unless, is_human
from .screen_workflow_bundle import load_bundle
from .screen_workflow_events import WorkflowRunsView, WorkflowRunView
from .screen_workflow_files import names
from .screen_workflow_parameters import Slug, Strict, WorkflowName

Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class Review(Strict):
    revision: Digest


class Decision(Strict):
    token: str = Field(min_length=1, max_length=80)
    allow: bool


class Start(Strict):
    workflow: WorkflowName
    window: str = Field(min_length=1, max_length=128)
    parameters: dict[Slug, JsonValue] = Field(default_factory=dict, max_length=32)
    client_key: str = Field(min_length=1, max_length=64)


class Resume(Strict):
    parameters: dict[Slug, JsonValue] | None = Field(default=None, max_length=32)


def summary(db, revision):
    approved = audit.approval(db, revision)
    return {
        "name": revision.workflow.name,
        "description": revision.workflow.description,
        "use_when": revision.workflow.use_when,
        "revision": revision.digest,
        "approved": bool(approved),
        "approved_by": approved["user_id"] if approved else None,
    }


def catalog(db, space):
    workflows = []
    for name in names(space):
        try:
            workflows.append(summary(db, load_bundle(space, name)))
        except (ValueError, OSError):
            workflows.append({"name": name, "error": "workflow is invalid or unavailable"})
    return {"workflows": workflows}


async def workflow_lab():
    return FileResponse(Path(__file__).with_name("static") / "lab" / "window-bench" / "workflow.html")


def workflows_router(service):
    db = service.db
    router = APIRouter(prefix="/api/conversations/{conv_id}/screen-workflows")

    async def human_only(request: Request):
        if not is_human(request_principal(request)):
            raise HTTPException(403, "workflow review, approval, confirmation and audit require a person")

    def authorize(request, conv_id, capability="read"):
        principal = request_principal(request)
        deny_unless(db, principal, conv_id, capability)
        return principal

    @router.get("")
    async def list_workflows(conv_id: str, request: Request):
        authorize(request, conv_id)
        space = await service.checkout(conv_id)
        try:
            return await asyncio.to_thread(catalog, db, space)
        except (ValueError, OSError) as exc:
            raise HTTPException(422, "workflow catalog unavailable") from exc

    @router.get("/definitions/{name}")
    async def show(conv_id: str, name: str, request: Request):
        authorize(request, conv_id)
        revision = await service.revision(conv_id, name)
        return {
            **summary(db, revision),
            "path": revision.path,
            "definition": revision.workflow.model_dump(exclude_none=True, by_alias=True),
            "bundle": revision.review(),
        }

    @router.get("/definitions/{name}/review", dependencies=[Depends(human_only)])
    async def review(conv_id: str, name: str, request: Request):
        return await show(conv_id, name, request)

    @router.put("/definitions/{name}/approval", dependencies=[Depends(human_only)])
    async def approve(conv_id: str, name: str, body: Review, request: Request):
        principal = authorize(request, conv_id, "write")
        revision = await service.revision(conv_id, name)
        if body.revision != revision.digest or not revision.current():
            raise HTTPException(409, "workflow changed. Review the current revision")
        audit.approve(db, revision, principal.user_id)
        try:
            await service.skills.mount(conv_id)
        except OSError:
            pass  # the ready approval remains discoverable through MCP
        return summary(db, revision)

    @router.delete("/definitions/{name}/approval", dependencies=[Depends(human_only)])
    async def revoke(conv_id: str, name: str, request: Request):
        authorize(request, conv_id, "write")
        space = await service.checkout(conv_id)
        # Invalidation must also work after the YAML becomes invalid or disappears.
        from .screen_workflow_format import workflow_name

        try:
            workflow_name(name)
        except ValueError as exc:
            raise HTTPException(422, "invalid workflow name") from exc
        paths = [
            path.relative_to(space.root).as_posix()
            for path in (folder / f"{name}.yaml" for folder in space.folders())
        ]
        for path in paths:
            db._exec(
                "DELETE FROM screen_workflow_approvals WHERE project=? AND checkout=? AND path=?",
                (space.project, os.path.normcase(str(space.root)), path),
            )
        return {"ok": True}

    @router.post("/runs", response_model=WorkflowRunView, response_model_exclude_unset=True)
    async def start(conv_id: str, body: Start, request: Request):
        principal = authorize(request, conv_id, "write")
        deny_unless(db, principal, conv_id, "read")
        return await service.start(principal, conv_id, body)

    @router.get("/runs", response_model=WorkflowRunsView, response_model_exclude_unset=True)
    async def list_runs(conv_id: str, request: Request):
        return {"runs": service.list_runs(authorize(request, conv_id), conv_id)}

    @router.post("/runs/{run_id}/resume", response_model=WorkflowRunView, response_model_exclude_unset=True)
    async def resume(conv_id: str, run_id: str, body: Resume, request: Request):
        principal = authorize(request, conv_id, "write")
        deny_unless(db, principal, conv_id, "read")
        return await service.resume(principal, conv_id, run_id, body.parameters)

    @router.get("/runs/{run_id}", response_model=WorkflowRunView, response_model_exclude_unset=True)
    async def status(conv_id: str, run_id: str, request: Request):
        return service.status(authorize(request, conv_id), conv_id, run_id)

    @router.post("/runs/{run_id}/stop", response_model=WorkflowRunView, response_model_exclude_unset=True)
    async def stop(conv_id: str, run_id: str, request: Request):
        return service.stop(authorize(request, conv_id, "write"), conv_id, run_id)

    @router.post("/runs/{run_id}/confirmation", dependencies=[Depends(human_only)])
    async def confirm(conv_id: str, run_id: str, body: Decision, request: Request):
        principal = authorize(request, conv_id, "write")
        return service.decide(principal, conv_id, run_id, body)

    @router.get("/runs/{run_id}/audit", dependencies=[Depends(human_only)])
    async def run_audit(conv_id: str, run_id: str, request: Request):
        authorize(request, conv_id)
        row = service.row(conv_id, run_id)
        if not row:
            raise HTTPException(404, "workflow run not found")
        metadata = (
            "actor",
            "actor_user_id",
            "attachment_id",
            "resume_attachment_id",
            "path",
            "grant_id",
            "started_at",
            "finished_at",
        )
        events = db._exec(
            "SELECT created_at,step,step_index,source,event,request_id,actor_user_id,actor_attachment_id,"
            "outcome FROM screen_workflow_events WHERE run_id=? ORDER BY id",
            (run_id,),
        ).fetchall()
        allowance = min(row["total_steps"], audit.MAX_RUN_RETRIES)
        retries = sum(1 for event in events if (event["outcome"] or "").startswith("retry;"))
        return {
            **audit.view(row),
            "action_budget": row["total_steps"],
            "retry_allowance": allowance,
            "retries_remaining": max(0, allowance - retries),
            **{key: row[key] for key in metadata},
            "events": [dict(event) for event in events],
        }

    return router
