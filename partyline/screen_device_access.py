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


def standing_roots(db, device) -> set[str]:
    """Person-approved roots, only while the paired owner still exists and can read them."""
    from .auth_store import user_by_id

    owner = user_by_id(db, device.get("owner_id"))
    if owner is None:
        return set()
    principal = Principal(kind="user", user_id=owner["id"], name=owner["handle"])
    rows = db._exec("SELECT a.conv_id FROM screen_device_window_lines a "
                   "JOIN screen_devices d ON d.id=a.device_id "
                   "WHERE d.id=? AND d.owner_id=? AND d.revoked_at IS NULL",
                   (device.get("id"), owner["id"])).fetchall()
    return {row["conv_id"] for row in rows if allows(db, principal, row["conv_id"], "read")}


def standing_lines(db, device) -> set[str]:
    """The live subtrees of all authorized roots; archived ancestors deny access."""
    roots = standing_roots(db, device)
    if not roots:
        return set()
    # One hierarchy read for the rail's entire snapshot, rather than a query
    # for every ancestor of every line. A missing (archived) parent denies.
    live = {line["id"]: line for line in db.list_conversations()}
    authorized = set()
    for ident in live:
        chain, current = set(), ident
        while current and current in live and current not in chain:
            chain.add(current)
            current = live[current].get("parent_id")
        if not current and chain & roots:
            authorized.add(ident)
    return authorized


def live_ancestry(db, conv_id) -> set[str]:
    chain = {conv_id, *ancestors(db, conv_id)}
    for ident in chain:
        line = db.get_conversation(ident)
        if not line or line.get("archived_at"):
            return set()
    return chain


def standing_devices(hub, conv_id: str) -> list[dict]:
    """Devices explicitly paired to this line or one of its ancestors by their owner."""
    db = getattr(getattr(hub, "runtime", None), "db", None)
    if db is None or not conv_id:
        return []
    owner_lines = live_ancestry(db, conv_id)
    return [device for device in getattr(hub, "devices", {}).values()
            if device.get("window_access_enabled") and standing_roots(db, device) & owner_lines]


def initialize_standing(db, device_id, conv_id):
    """Pairing from a line selects it; account pairing starts with an empty set."""
    db._exec("INSERT INTO screen_device_window_access(device_id,enabled) VALUES(?,0)", (device_id,))
    if conv_id:
        db._exec("INSERT INTO screen_device_window_lines(device_id,conv_id) VALUES(?,?)",
                 (device_id, conv_id))
