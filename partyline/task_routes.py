"""REST routes for a line's shared task board."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .contracts import OkResponse
from .task_contracts import Task, TaskCreateRequest, TaskUpdateRequest
from .tasks import UNSET, TaskError, TaskStore


def _http(exc: TaskError) -> HTTPException:
    return HTTPException(exc.status_code, exc.detail)


def task_router(runtime, store: TaskStore) -> APIRouter:
    """Bind task routes to one runtime and its task store."""
    router = APIRouter()

    def require_line(conv_id: str, *, writing: bool):
        conv = runtime.db.get_conversation(conv_id)
        if not conv:
            raise HTTPException(404)
        if writing and conv["archived_at"]:
            raise HTTPException(409, "restore the line before changing its tasks")

    @router.get("/api/conversations/{conv_id}/tasks", response_model=list[Task])
    def list_tasks(conv_id: str, status: str | None = None):
        require_line(conv_id, writing=False)
        try:
            return store.list(conv_id, status=status)
        except TaskError as exc:
            raise _http(exc) from exc

    @router.post(
        "/api/conversations/{conv_id}/tasks", response_model=Task, status_code=201)
    def create_task(conv_id: str, body: TaskCreateRequest):
        require_line(conv_id, writing=True)
        try:
            return store.add(conv_id, body.body, body.owner)
        except TaskError as exc:  # pragma: no cover — pydantic validates first;
            raise _http(exc) from exc  # the store's own checks guard direct callers

    @router.patch("/api/tasks/{task_id}", response_model=Task)
    def update_task(task_id: int, body: TaskUpdateRequest):
        provided = body.model_fields_set
        try:
            task = store.get(task_id)
        except TaskError as exc:
            raise _http(exc) from exc
        require_line(task["conv_id"], writing=True)
        try:
            return store.update(
                task_id,
                body=body.body if "body" in provided else UNSET,
                status=body.status if "status" in provided else UNSET,
                owner=body.owner if "owner" in provided else UNSET,
            )
        except TaskError as exc:  # pragma: no cover — pydantic validates first;
            raise _http(exc) from exc  # the store's own checks guard direct callers

    @router.delete("/api/tasks/{task_id}", response_model=OkResponse)
    def delete_task(task_id: int):
        try:
            task = store.get(task_id)
        except TaskError as exc:
            raise _http(exc) from exc
        require_line(task["conv_id"], writing=True)
        store.delete(task_id)
        return OkResponse(ok=True)

    return router


def wire_tasks(app, runtime) -> TaskStore:
    """Create a line's task store and mount its routes, in one server.py line."""
    store = TaskStore(runtime.db)
    app.include_router(task_router(runtime, store))
    return store
