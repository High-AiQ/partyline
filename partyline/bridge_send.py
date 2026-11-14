"""The ``bridge_send`` tool's server side: speak over the caller's open bridge.

The words go through the same stamp, rate limit, audit row and copy as an
``@[bridge]`` message; they are just not entangled with the turn's final text, so
an ambassador can answer its peer and still tell its own people in the same turn.
Nothing is posted to either line's chat: the row carries the bridge id, which
hides it from every reader but the bridge log.
"""

from fastapi import HTTPException

from .bridge_delivery import deliver_copy
from .bridge_store import open_bridge_for_attachment, side, side_view
from .hierarchy import stamp_source
from .idempotent_posts import claim_key, original_for_key, principal_identity, remember_key
from .message_queries import select_message_by_id

REFUSED = {"limit": 429, "closed": 409, "gone": 409}


async def send(runtime, principal, conv_id: str, text: str, client_key: str | None) -> dict:
    db = runtime.db
    if principal.kind != "machine" or principal.conv_id != conv_id:
        raise HTTPException(403, "bridge_send is for this line's ambassador, on its own line")
    bridge = open_bridge_for_attachment(db, principal.attachment_id)
    if bridge is None:
        raise HTTPException(409, "no open bridge: this line's bridge is closed or you are "
                                 "not its ambassador, so nothing crossed")
    if not text.strip():
        raise HTTPException(400, "message text is required")
    caller = principal_identity(principal)
    if not client_key:
        return await _send(runtime, principal, conv_id, bridge, text, None, caller)
    async with claim_key(db, caller, conv_id, client_key):
        if (original := original_for_key(db, caller, client_key, conv_id)) is not None:
            return {"status": "already sent", "replayed": True, "message_id": original["id"]}
        return await _send(runtime, principal, conv_id, bridge, text, client_key, caller)


async def _send(runtime, principal, conv_id, bridge, text, client_key, caller) -> dict:
    db = runtime.db
    stored = db.add_message(conv_id, principal.name, "agent", text)
    stamp_source(db, stored["id"], principal)
    db._exec("UPDATE messages SET bridge_id=? WHERE id=?", (bridge["id"], stored["id"]))
    db._exec("INSERT OR IGNORE INTO bridge_tool_sends(message_id) VALUES(?)", (stored["id"],))
    message = select_message_by_id(db._exec, conv_id, stored["id"])
    status, note = await deliver_copy(runtime, conv_id, message)
    if status in REFUSED:
        raise HTTPException(REFUSED[status], note)
    if client_key:
        remember_key(db, caller, client_key, conv_id, stored["id"])
    peer = side_view(db, bridge, side(bridge, principal.attachment_id)[1])
    return {"status": status, "to": peer["name"], "line": peer["conv_name"],
            "message_id": stored["id"], **({"note": note} if note else {})}
