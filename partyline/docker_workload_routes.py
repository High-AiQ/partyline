"""Docker workloads: read the inventory, stop one container by id."""

from fastapi import Request

from .auth_guard import request_principal
from .docker_workloads import inventory, stop_owned
from .machine_scope import is_human, visible_conversation_ids


def register_docker_workload_routes(app, runtime) -> None:
    @app.get("/api/docker-workloads")
    async def workloads(request: Request):
        principal = request_principal(request)
        await inventory.sample(runtime)
        visible = None if is_human(principal) else visible_conversation_ids(runtime.db, principal)
        return inventory.view(runtime.db, visible)

    @app.post("/api/docker-workloads/{container_id}/stop")
    async def stop(request: Request, container_id: str):
        return await stop_owned(runtime, request_principal(request), container_id)
