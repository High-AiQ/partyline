"""Authenticated fleet-wide capacity visibility and people-only settings."""

from fastapi import HTTPException, Request

from .auth_guard import request_principal
from .resource_budget import memory_ceiling, settings, snapshot, validate_settings
from .resource_contracts import ResourceSettings, ResourceSettingsIn, ResourceSnapshot

KEYS = ("max_live_processes", "memory_reserve_bytes", "default_process_memory_bytes")


def register_resource_routes(app, runtime) -> None:
    @app.get("/api/resources", response_model=ResourceSnapshot)
    def resources(request: Request):
        request_principal(request)  # all authenticated people and machines may read
        view = snapshot(runtime.db)
        return {**view, "memory_ceiling_bytes": memory_ceiling()}

    @app.get("/api/settings/resources", response_model=ResourceSettings)
    def get_resource_settings(request: Request):
        _require_person(request)
        host = _host()
        current = settings(runtime.db, host)
        return {
            **current,
            "host_ram_bytes": host.ram_bytes,
            "memory_budget_bytes": max(0, host.ram_bytes-current["memory_reserve_bytes"]),
            "memory_ceiling_bytes": memory_ceiling(host),
        }

    @app.put("/api/settings/resources", response_model=ResourceSettings)
    async def put_resource_settings(request: Request, body: ResourceSettingsIn):
        _require_person(request)
        host = _host()
        values = body.model_dump()
        try:
            validate_settings(values, host)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        async with runtime.db._runtime_serialized_async():
            with runtime.db.lock, runtime.db.conn:
                for key in KEYS:
                    runtime.db.conn.execute(
                        "INSERT INTO settings(key,value) VALUES(?,?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, str(values[key])),
                    )
        return {
            **values,
            "host_ram_bytes": host.ram_bytes,
            "memory_budget_bytes": host.ram_bytes-values["memory_reserve_bytes"],
            "memory_ceiling_bytes": memory_ceiling(host),
        }

    def _host():
        from .resource_budget import host_resources
        return host_resources()

    def _require_person(request: Request) -> None:
        if request_principal(request).kind != "user":
            raise HTTPException(403, "only people can change instance resource settings")
