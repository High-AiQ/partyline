"""Owner-scoped screen state delivered to each chat socket."""

from .op_timing import pushed
from .helper_release import update_available
from .screen_grants import device_grants
from .screen_device_access import standing_roots, standing_lines, standing_devices


def owner_devices(hub, owner_id):
    rows = hub.runtime.db._exec(
        "SELECT id,name,os,created_at FROM screen_devices WHERE owner_id=? "
        "AND revoked_at IS NULL ORDER BY created_at", (owner_id,)).fetchall()
    devices = []
    for row in rows:
        item = dict(row)
        online = hub.devices.get(item["id"])
        preference = hub.runtime.db._exec("SELECT enabled FROM screen_helper_preferences WHERE device_id=?",
                                          (item["id"],)).fetchone()
        item["auto_update"] = bool(preference and preference["enabled"])
        item["updating"] = bool(getattr(hub, "updates", None) and hub.updates.paused(item["id"]))
        grants = device_grants(hub.runtime.db, item["id"])
        for grant in grants:
            if shot := hub.snapshots.last_screenshot(grant["id"]):
                grant["last_screenshot"] = shot  # when an agent last took a screenshot, and who
        roots = sorted(standing_roots(hub.runtime.db, {**item, "owner_id": owner_id}))
        item.update(window_access_line=roots[0] if roots else None, window_access_lines=roots,
                    chrome=online.get("chrome") if online else None, window_grants=grants,
                    online=online is not None, monitors=online["monitors"] if online else [],
                    helper_version=online["helper_version"] if online else None,
                    update_available=bool(online) and update_available(online["helper_version"]))
        devices.append(item)
    return devices


def owner_indicators(hub, owner_id):
    indicators = []
    for share in hub.shares.values():
        device = hub.devices.get(share.device_id)
        if share.owner_id == owner_id and share.status == "active" and device:
            name = device["name"]
            indicators.append({"conv_id": share.conv_id, "device_name": name,
                               "kind": "screen", "label": f"{name} screen share"})
    for device in hub.devices.values():
        if device["owner_id"] != owner_id:
            continue
        for grant in device_grants(hub.runtime.db, device["id"]):
            if grant["standing_access"] and device not in standing_devices(hub, grant["conv_id"]):
                continue
            indicators.append({"conv_id": grant["conv_id"], "device_name": device["name"],
                               "kind": "window", "label":
                               f"window → «{grant['line_name']}» (and its sublines): {grant['title']}"})
    for device in hub.devices.values():
        if device["owner_id"] != owner_id or not device.get("window_access_enabled"):
            continue
        for ident in sorted(standing_lines(hub.runtime.db, device)):
            indicators.append({"conv_id": ident, "device_name": device["name"],
                               "kind": "standing", "label": f"{device['name']} window access available"})
    return indicators


def owner_state(hub, owner_id):
    return owner_devices(hub, owner_id), owner_indicators(hub, owner_id)


def snapshot(hub, owner_id, conv_id, state=None):
    devices, indicators = state if state is not None else owner_state(hub, owner_id)
    share = hub.shares.get(conv_id)
    device = hub.devices.get(share.device_id) if share else None
    return {"type": "screen_snapshot", "indicators": indicators, "devices": devices,
            "share": hub._share_view(share, device)["share"] if share and device else None}


async def send_snapshot(runtime, ws, conv_id):
    hub = getattr(runtime, "screen_hub", None)
    owner_id = getattr(ws, "screen_owner_id", None)
    if hub is not None and owner_id is not None:
        await pushed("screen", ws.send_json(snapshot(hub, owner_id, conv_id)))


async def refresh_snapshots(runtime):
    """Build once per owner across all tabs; screen failures never evict chat sockets."""
    hub = getattr(runtime, "screen_hub", None)
    if hub is None:
        return
    states = {}
    for conv_id, sockets in list(runtime.sockets.items()):
        for ws in list(sockets):
            owner_id = getattr(ws, "screen_owner_id", None)
            if owner_id is None:
                continue
            try:
                if owner_id not in states:
                    states[owner_id] = None  # cache failures too, without leaking another owner's state
                    states[owner_id] = owner_state(hub, owner_id)
                if states[owner_id] is not None:
                    await pushed("screen", ws.send_json(snapshot(hub, owner_id, conv_id, states[owner_id])))
            except Exception:
                # The next device/hierarchy event or reconnect will send a fresh snapshot.
                # Chat's own send path alone decides whether a socket is dead.
                pass
