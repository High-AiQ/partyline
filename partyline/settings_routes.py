"""REST routes for instance-wide settings."""

from fastapi import APIRouter, HTTPException, Request

from .auth_guard import request_principal
from .settings_contracts import GlobalProseIn, GlobalProseResponse
from .orchestrator_contracts import AutoCleanIn


def settings_router(runtime) -> APIRouter:
    router = APIRouter()

    @router.get("/api/settings/global_prose", response_model=GlobalProseResponse)
    def get_global_prose(request: Request):
        _require_human(request)
        return {"value": runtime.db.get_setting("global_prose")}

    @router.put("/api/settings/global_prose", response_model=GlobalProseResponse)
    def put_global_prose(request: Request, body: GlobalProseIn):
        _require_human(request)
        return {"value": runtime.db.set_setting("global_prose", body.value)}

    @router.get("/api/settings/auto_clean_task_history", response_model=AutoCleanIn)
    def get_auto_clean(request: Request):
        _require_human(request)
        return {"enabled": runtime.db.get_setting("auto_clean_task_history") == "true"}

    @router.put("/api/settings/auto_clean_task_history", response_model=AutoCleanIn)
    def put_auto_clean(request: Request, body: AutoCleanIn):
        _require_human(request)
        runtime.db.set_setting("auto_clean_task_history", "true" if body.enabled else "false")
        return body

    def _require_human(request: Request) -> None:
        if request_principal(request).kind != "user":
            raise HTTPException(403, "only people can change instance settings")

    return router
