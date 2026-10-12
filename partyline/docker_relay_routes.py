"""Where each docker relay stands: for a person, or the captain of the line."""

from fastapi import HTTPException, Request

from . import docker_relay
from .auth_guard import request_principal
from .machine_scope import is_human


def register_docker_relay_routes(app) -> None:
    @app.get("/api/docker-relay")
    async def relay_status(request: Request):
        principal = request_principal(request)
        if not is_human(principal) and not principal.is_lead:
            raise HTTPException(403, "only a person or a line's captain may read relay status")
        rows = await docker_relay.status()
        if is_human(principal):
            return rows
        return [row for row in rows if row["conv_id"] == principal.conv_id]
