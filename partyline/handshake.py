"""Pure construction of server identity payloads."""

from pydantic import BaseModel

from .contracts import HelloEvent


class VersionResponse(BaseModel):
    version: str
    build: str
    instance_name: str | None = None
    # Which checkout the running process serves from, and the commit it
    # started on: what a restart would deploy. Both None outside git.
    checkout_path: str | None = None
    git_head: str | None = None


def hello_payload(
    conversation_id: str,
    handle: str,
    frontend_build: str,
    server_version: str,
    instance_name: str | None,
) -> dict:
    """Build the authoritative identity sent on every WebSocket handshake."""
    return HelloEvent(
        conversation_id=conversation_id,
        handle=handle,
        build=frontend_build or None,
        version=server_version,
        instance_name=instance_name,
    ).model_dump(exclude_none=True)
