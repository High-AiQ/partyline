"""Routes for window trees, element actions, and screen evaluation."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from . import screen_elements as core
from .screen_element_actions import ElementAction
from .screen_eval import ScreenEval
from .screen_tree_answer import elements_options

ELEMENT_OPTIONS = Annotated[dict, Depends(elements_options)]


def elements_router(runtime, hub, store=None):
    router = APIRouter()

    @router.post("/api/conversations/{conv_id}/screen-elements")
    @core.timed
    async def elements(conv_id: str, request: Request, options: ELEMENT_OPTIONS,
                       device: str | None = None, window: str | None = None):
        principal = core.request_principal(request)
        core.deny_unless(runtime.db, principal, conv_id, "read")
        grant, _ = core.resolve_window(hub, principal, window, device)
        core.audit_call(hub, principal, grant, "screen_elements")
        await core.record_standing_window_access(runtime, hub, principal, conv_id, "uia_read", window, device,
                                                 "started")
        try:
            result = await hub.elements.read(principal, device, window, options)
        except HTTPException:
            from .screen_workflow_learning import record_call
            record_call(runtime.db, grant["id"], "screen_elements", options, "failed")
            await core.record_standing_window_access(
                runtime, hub, principal, conv_id, "uia_read", window, device, "failed")
            raise
        from .screen_workflow_learning import read_observation, record_call
        tree = hub.elements.fresh(grant["id"])
        record_call(runtime.db, grant["id"], "screen_elements", options,
                    "unavailable" if result.get("elements_unavailable") else "returned",
                    read_observation(tree, result))
        await core.record_standing_window_access(runtime, hub, principal, conv_id, "uia_read", window, device,
                                                 "failed" if result.get("elements_unavailable") else "read")
        return result

    @router.post("/api/conversations/{conv_id}/screen-control/element-action")
    async def act(conv_id: str, body: ElementAction, request: Request):
        principal = core.request_principal(request)
        core.deny_unless(runtime.db, principal, conv_id, "write")
        try:
            grant, device = core.resolve_window(hub, principal, body.window)
        except HTTPException as exc:
            if body.action == "set_files":
                raise HTTPException(exc.status_code, str(exc.detail) +
                                    "; use the Open dialog path instead") from exc
            raise
        if body.action == "set_values":
            if body.then:
                core.deny_unless(runtime.db, principal, conv_id, "read")
            needs_fill_guard = any(item.when or item.action == "select" for item in body.assignments)
            if needs_fill_guard and device.get("chrome_dom", 0) < 6:
                raise HTTPException(409, "update the Partyline helper to use guarded grouped form filling")
            from .screen_form_actions import act as form_action
            return await form_action(runtime, hub, conv_id, body, principal, grant, device)
        core.audit_call(hub, principal, grant, "screen_element_action", len(body.value or body.key or ""))
        if body.then:
            core.deny_unless(runtime.db, principal, conv_id, "read")
        call = "uia_action"
        if body.mark is not None:
            _, _, node = hub.snapshots.looks.target(principal, grant, body.mark)
            if body.action in ("invoke", "click") and body.action not in node.actions:
                call = None  # point_operation owns the standing audit for this input
        if call:
            await core.record_standing_window_access(
                runtime, hub, principal, conv_id, call, body.window, None, "started")
        try:
            if body.mark is not None:
                from .screen_window_look import mark_action
                result = await mark_action(runtime, hub, store, conv_id, body, request)
            else:
                result = await core.element_action(runtime, hub, conv_id, body, request)
        except HTTPException:
            from .screen_workflow_learning import record_call
            record_call(runtime.db, grant["id"], "screen_element_action",
                        body.model_dump(exclude_none=True), "failed")
            if call:
                await core.record_standing_window_access(
                    runtime, hub, principal, conv_id, call, body.window, None, "failed")
            raise
        from .screen_workflow_learning import read_observation, record_call
        tree = hub.elements.fresh(grant["id"])
        record_call(runtime.db, grant["id"], "screen_element_action",
                    body.model_dump(exclude_none=True), result.get("status", "returned"),
                    read_observation(tree, result.get("after")))
        if call:
            await core.record_standing_window_access(
                runtime, hub, principal, conv_id, call, body.window, None, result.get("status", "failed"))
        if store is not None:
            from .screen_failure_snapshot import attach, failed
            if failed(result):  # a failure a picture explains carries one, with marks
                await attach(runtime, hub, store, principal, conv_id, grant, result)
            elif body.then and body.then.snapshot and result.get("status") in ("completed", "no_effect"):
                await attach(runtime, hub, store, principal, conv_id, grant, result, marks=False)
        return result

    @router.post("/api/conversations/{conv_id}/screen-eval")
    async def evaluate(conv_id: str, body: ScreenEval, request: Request):
        return await core.screen_eval(runtime, hub, conv_id, body, request)

    return router
