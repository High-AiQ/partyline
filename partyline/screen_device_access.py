"""Online helpers owned by people who can read a line."""

from .auth_guard import Principal
from .hierarchy import ancestors
from .machine_scope import allows


def connected_device(device, socket, hello):
    """Merge the helper's authenticated hello with the paired device record."""
    return {**device, "socket": socket, "name": hello.device_name, "os": hello.os,
            "helper_version": hello.helper_version, "control": hello.control,
            "tools": hello.tools, "windows": hello.windows, "press": hello.press,
            "chrome_dom": hello.chrome_dom,
            "chrome": hello.chrome.model_dump() if hello.chrome else None,
            "window_access_enabled": hello.window_access,
            "monitors": [item.model_dump() for item in hello.monitors]}


def line_devices(hub, conv_id: str, name: str | None = None, db=None) -> list[dict]:
    db = db or getattr(getattr(hub, "runtime", None), "db", None)
    if db is None:
        return []
    users = db._exec("SELECT id,handle FROM users").fetchall() if db.get_conversation(conv_id) else []
    owners = set()
    for row in users:
        handle = row["handle"] if "handle" in row.keys() else ""
        if allows(db, Principal(kind="user", user_id=row["id"], name=handle), conv_id, "read"):
            owners.add(row["id"])
    return [device for device in getattr(hub, "devices", {}).values()
            if device["owner_id"] in owners and (name is None or device["name"] == name)]


def standing_root(db, device) -> str | None:
    """The line the person paired from, separate from account-wide screen-sharing scope."""
    row = db._exec("SELECT owner_conv_id FROM screen_device_window_access WHERE device_id=?",
                   (device.get("id"),)).fetchone()
    root = row["owner_conv_id"] if row else None
    return root or device.get("conv_id")


def standing_devices(hub, conv_id: str) -> list[dict]:
    """Devices explicitly paired to this line or one of its ancestors by their owner."""
    db = getattr(getattr(hub, "runtime", None), "db", None)
    if db is None or not conv_id:
        return []
    line = db.get_conversation(conv_id)
    if not line or line.get("archived_at"):
        return []
    owner_lines = {conv_id}
    for ancestor_id in ancestors(db, conv_id):
        ancestor = db.get_conversation(ancestor_id)
        if not ancestor or ancestor.get("archived_at"):
            return []
        owner_lines.add(ancestor_id)
    return [device for device in getattr(hub, "devices", {}).values()
            if device.get("window_access_enabled") and standing_root(db, device) in owner_lines]
