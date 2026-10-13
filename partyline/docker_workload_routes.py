"""Docker workloads: read the inventory, stop one container by id."""

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from .auth_guard import request_principal
from .docker_gpu import gpu, slots
from .docker_workloads import inventory, stop_owned
from .machine_scope import is_human, visible_conversation_ids


class GpuSettingsIn(BaseModel):
    slots: int = Field(ge=1, le=8)


def register_docker_workload_routes(app, runtime) -> None:
    def person(request: Request) -> None:
        if not is_human(request_principal(request)):
            raise HTTPException(403, "only a person may change GPU admission")

    @app.get("/api/docker-workloads")
    async def workloads(request: Request):
        principal = request_principal(request)
        await inventory.sample(runtime)
        visible = None if is_human(principal) else visible_conversation_ids(runtime.db, principal)
        return inventory.view(runtime.db, visible)

    @app.post("/api/docker-workloads/{container_id}/stop")
    async def stop(request: Request, container_id: str):
        return await stop_owned(runtime, request_principal(request), container_id)

    @app.get("/api/docker-gpu")
    async def gpu_state(request: Request):
        request_principal(request)
        return {"unhealthy": gpu.unhealthy, "slots": slots(runtime.db)}

    @app.post("/api/docker-gpu/clear")
    async def gpu_clear(request: Request):
        person(request)
        gpu.clear()
        return {"unhealthy": None}

    @app.put("/api/docker-gpu")
    async def gpu_slots(request: Request, body: GpuSettingsIn):
        person(request)
        runtime.db.set_setting("docker_gpu_slots", str(body.slots))
        return {"unhealthy": gpu.unhealthy, "slots": body.slots}
