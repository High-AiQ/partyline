"""Online helpers owned by people who can read a line."""

from .auth_guard import Principal
from .machine_scope import allows


def line_devices(hub, conv_id: str, name: str | None = None) -> list[dict]:
    db = hub.runtime.db
    users = db._exec("SELECT id,handle FROM users").fetchall() if db.get_conversation(conv_id) else []
    owners = {row["id"] for row in users
              if allows(db, Principal(kind="user", user_id=row["id"], name=row["handle"]), conv_id, "read")}
    return [device for device in hub.devices.values()
            if device["owner_id"] in owners and (name is None or device["name"] == name)]
