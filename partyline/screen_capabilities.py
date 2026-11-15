"""Screen access flags included with an attachment's MCP capabilities."""

def for_request(runtime, db, request, conv_id, capability_resolver):
    from .auth_guard import request_principal
    principal = request_principal(request)
    versions = getattr(runtime, "capability_versions", None)
    if principal.kind != "machine" or versions is None:
        return capability_resolver(db, principal, conv_id)
    version = versions.current(principal.attachment_id)
    while True:
        state = capability_resolver(db, principal, conv_id)
        state = for_attachment(runtime, principal, conv_id, state)
        current = versions.current(principal.attachment_id)
        if current == version:
            state["capability_version"] = current
            return state
        version = current


def for_attachment(runtime, principal, conv_id, state):
    if principal.kind != "machine" or (conv_id and conv_id != principal.conv_id):
        return state
    att = runtime.db.get_attachment(principal.attachment_id)
    if att is None:
        return state
    # Only clients with measured list_changed support may hide access-bound tools.
    state["dynamic_screen_tools"] = att.get("adapter") in {"claude", "opencode-v2"}
    from .bridge_store import open_bridge_for_attachment
    state["bridge_open"] = open_bridge_for_attachment(runtime.db, principal.attachment_id) is not None
    hub = getattr(runtime, "screen_hub", None)
    if hub is None:
        return state
    share = hub.shares.get(principal.conv_id)
    state["screen_read"] = bool(share and share.status == "active")
    grant = hub.control.grants.get(share.share_id) if share and share.status == "active" else None
    state["screen_control"] = bool(
        grant and grant.status == "active" and grant.holder in (None, principal.name))
    from .screen_device_access import line_devices
    devices = line_devices(hub, principal.conv_id, db=runtime.db)
    state["window_access"] = any(device.get("window_access_enabled", False) for device in devices)
    from .screen_grants import line_grants
    state["screen_windows"] = bool(line_grants(runtime.db, principal.conv_id))
    return state
