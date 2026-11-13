"""REST routes for instance-wide settings."""

import time

from fastapi import APIRouter, HTTPException, Request

from .auth_guard import request_principal
from .compaction_limit import SETTING as MAX_COMPACTIONS, global_limit
from .settings_contracts import GlobalProseIn, GlobalProseResponse, MaxCompactionsIn
from .orchestrator_contracts import AutoCleanIn
from .review_environments import Environments
from .review_env_operations import ReviewEnvOperation, operate


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

    @router.get("/api/settings/max_compactions", response_model=MaxCompactionsIn)
    def get_max_compactions(request: Request):
        _require_human(request)
        return {"value": global_limit(runtime.db)}

    @router.put("/api/settings/max_compactions", response_model=MaxCompactionsIn)
    def put_max_compactions(request: Request, body: MaxCompactionsIn):
        _require_human(request)
        runtime.db.set_setting(MAX_COMPACTIONS, str(body.value))
        return body

    @router.get("/api/settings/review-environments", response_model=Environments)
    def get_review_environments(request: Request):
        _require_human(request)
        rows = runtime.db._exec("SELECT * FROM review_environments ORDER BY repository, subpath").fetchall()
        return {"entries": [dict(row) for row in rows]}

    @router.put("/api/settings/review-environments", response_model=Environments)
    def put_review_environments(request: Request, body: Environments):
        _require_human(request)
        with runtime.db.lock, runtime.db.conn:
            old = {(row['repository'], row['subpath']): dict(row) for row in
                   runtime.db.conn.execute("SELECT * FROM review_environments")}
            runtime.db.conn.execute("DELETE FROM review_environments")
            for entry in body.entries:
                previous = old.get((entry.repository, entry.subpath))
                unchanged = (previous and previous['setup_command'] == entry.setup_command
                             and previous['test_command'] == entry.test_command)
                who = previous['set_by'] if unchanged else request_principal(request).name
                when = previous['set_at'] if unchanged else time.time()
                runtime.db.conn.execute("INSERT INTO review_environments VALUES(?,?,?,?,?,?)",
                                        (entry.repository, entry.subpath, entry.setup_command,
                                         entry.test_command, who, when))
        return get_review_environments(request)

    @router.post("/api/conversations/{conv_id}/review-environment")
    async def review_environment(request: Request, conv_id: str, body: ReviewEnvOperation):
        return await operate(runtime, request_principal(request), conv_id, body)

    def _require_human(request: Request) -> None:
        if request_principal(request).kind != "user":
            raise HTTPException(403, "only people can change instance settings")

    return router
