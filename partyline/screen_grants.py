"""Resolve UI Automation access by window grant and attachment identity."""
from fastapi import APIRouter, HTTPException, Request

from .auth_guard import request_principal
from .machine_scope import is_human


GRANTS = ("SELECT g.id,g.device_id,g.attachment_id,g.title,g.process,g.hwnd,"
          "a.name AS holder,a.conv_id,c.name AS line_name,d.owner_id,d.name AS device_name "
          "FROM screen_window_grants g "
          "JOIN attachments a ON a.id=g.attachment_id JOIN conversations c ON c.id=a.conv_id "
          "JOIN screen_devices d ON d.id=g.device_id WHERE d.revoked_at IS NULL "
          "AND a.status IN ('starting','running') AND a.runtime_owner IS g.runtime_owner")


def device_grants(db, device_id):
    return [dict(row) for row in db._exec(GRANTS + " AND g.device_id=?", (device_id,)).fetchall()]


def resolve_window(hub, principal, window=None, device_name=None):
    rows = [dict(row) for row in hub.runtime.db._exec(GRANTS).fetchall()]
    online = [g for g in rows if g["device_id"] in hub.devices]
    owners = {g["owner_id"] for g in online
              if g["attachment_id"] == getattr(principal, "attachment_id", None)}
    if device_name:
        online = [g for g in online if hub.devices[g["device_id"]]["name"] == device_name]
    if is_human(principal):
        relevant = [g for g in online if g["owner_id"] == principal.user_id]
        own = relevant
    else:
        own = [g for g in online if g["attachment_id"] == principal.attachment_id]
        # Without a grant, name only holders already sharing into the caller's line.
        relevant = [g for g in online if (g["owner_id"] in owners if owners
                                         else g["conv_id"] == principal.conv_id)]
    if window:
        matches = [g for g in own if window in (g["id"], g["title"])]
        if not matches:
            held = [g for g in relevant if window in (g["id"], g["title"])]
            refuse(held)
        own = matches
    if not own:
        refuse(relevant)
    if len(own) != 1:
        choices = "; ".join(f"{g['id']}: {g['title']} ({g['process']})" for g in own)
        raise HTTPException(409, "Several windows are shared with you; "
                            "specify window by grant id or title: " + choices)
    grant = own[0]
    return grant, hub.devices[grant["device_id"]]


def refuse(held):
    holders = ", ".join(sorted({f"@{g['holder']} on «{g['line_name']}»" for g in held}))
    detail = f"; current window holders: {holders}" if holders else ""
    raise HTTPException(403, "no window is shared with you" + detail + "; ask the person to share one")


def require_window(hub, principal, grant_id):
    # Re-check after awaits: detachment, revocation or replacement discards in-flight reads.
    return resolve_window(hub, principal, grant_id)


def window_share_indicators(db, owner_id):
    return [{"conv_id": g["conv_id"], "device_name": g["device_name"], "kind": "window",
             "label": f"reading {g['title']} for @{g['holder']}"} for g in
            db._exec(GRANTS + " AND d.owner_id=?",
                     (owner_id,)).fetchall()]


def grant_router(runtime, hub):
    router = APIRouter()

    @router.delete("/api/screen/window-grants/{grant_id}")
    async def revoke(grant_id: str, request: Request):
        principal = request_principal(request)
        if not is_human(principal):
            raise HTTPException(403, "window grants are managed by the computer's owner")
        row = runtime.db._exec(
            "SELECT g.id FROM screen_window_grants g JOIN screen_devices d ON d.id=g.device_id "
            "WHERE g.id=? AND d.owner_id=?", (grant_id, principal.user_id)).fetchone()
        if not row:
            raise HTTPException(404, "window grant not found")
        await hub.window_grants.revoke(grant_id)
        return {"ok": True}

    return router
