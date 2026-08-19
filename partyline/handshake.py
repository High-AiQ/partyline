"""Pure construction of server identity payloads."""

from .contracts import HelloEvent


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
