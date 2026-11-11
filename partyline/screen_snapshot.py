"""Owner-scoped screen state delivered to each chat socket."""

from .helper_release import update_available
from .screen_grants import device_grants, window_share_indicators


def owner_devices(hub, owner_id):
    rows = hub.runtime.db._exec(
        "SELECT id,name,os,created_at FROM screen_devices WHERE owner_id=? "
        "AND revoked_at IS NULL ORDER BY created_at", (owner_id,)).fetchall()
    devices = []
    for row in rows:
        item = dict(row)
        online = hub.devices.get(item["id"])
        item.update(window_grants=device_grants(hub.runtime.db, item["id"]),
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
    indicators.extend(window_share_indicators(hub.runtime.db, owner_id))
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
        await ws.send_json(snapshot(hub, owner_id, conv_id))
