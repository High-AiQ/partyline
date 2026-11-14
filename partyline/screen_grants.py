"""Resolve UI Automation access by window grant and attachment identity."""
from fastapi import APIRouter, HTTPException, Request

from .auth_guard import request_principal
from .hierarchy import ancestors
from .machine_scope import is_human, visible_conversation_ids


GRANTS = ("SELECT g.id,g.device_id,g.conv_id,g.title,g.process,g.hwnd,c.name AS line_name,"
          "d.owner_id,d.name AS device_name FROM screen_line_window_grants g "
          "JOIN conversations c ON c.id=g.conv_id AND c.archived_at IS NULL "
          "JOIN screen_devices d ON d.id=g.device_id WHERE d.revoked_at IS NULL")


def device_grants(db, device_id):
    return [dict(row) for row in db._exec(GRANTS + " AND g.device_id=?", (device_id,)).fetchall()]


def monitor_refusal(db, conv_id):
    """Why a monitor-capture tool has nothing to capture; with a window shared, where to look instead."""
    rows = sorted(line_grants(db, conv_id), key=lambda row: row["title"])
    if not rows:
        return "nobody is sharing a screen on this line"
    windows = "; ".join(f"window «{row['title']}» ({row['id']})" for row in rows)
    return (f"no monitor is shared with this line; {windows} is: use screen_window_snapshot(window=<id>) "
            "for a picture (extras(op=\"screen_window_snapshot\", args) if unlisted), or screen_elements "
            "first. Do not ask the person to share the whole screen")

def window_line_ids(db, conv_id):
    """Home and ancestors connected by live lines; an archived branch cannot inherit."""
    if not conv_id:
        return []
    result = []
    for ident in (conv_id, *ancestors(db, conv_id)):
        line = db.get_conversation(ident)
        if not line or line.get("archived_at"):
            break
        result.append(ident)
    return result


def line_grants(db, conv_id):
    lines = window_line_ids(db, conv_id)
    return [dict(row) for row in db._exec(GRANTS).fetchall() if row["conv_id"] in lines]


def resolve_window(hub, principal, window=None, device_name=None):
    """A person's own window, or one shared with the caller's line or its live ancestors."""
    rows = [dict(row) for row in hub.runtime.db._exec(GRANTS).fetchall()]
    online = [g for g in rows if g["device_id"] in hub.devices]
    if device_name:
        online = [g for g in online if hub.devices[g["device_id"]]["name"] == device_name]
    if is_human(principal):
        own = [g for g in online if g["owner_id"] == principal.user_id]
        relevant = None
    else:
        lines = window_line_ids(hub.runtime.db, principal.conv_id)
        own = [g for g in online if g["conv_id"] in lines]
        visible = visible_conversation_ids(hub.runtime.db, principal)  # never name a line it cannot see
        relevant = [g for g in online if g["conv_id"] not in lines and g["conv_id"] in visible]
    if window:
        matches = ([g for g in own if window == g["id"]] or
                   [g for g in own if window == g["title"]])
        if not matches:
            refuse([g for g in relevant or () if window in (g["id"], g["title"])], own, relevant is None)
        own = matches
    if not own:
        refuse(relevant or (), own, relevant is None)
    if len(own) != 1:
        choices = "; ".join(f"{g['id']}: {g['title']} ({g['process']}) → «{g['line_name']}»" for g in own)
        raise HTTPException(409, "Several windows are shared with you; "
                            "specify window by grant id or title: " + choices)
    grant = own[0]
    if not is_human(principal) and grant["conv_id"] != principal.conv_id:
        grant["inherited_from"] = grant["line_name"]
    return grant, hub.devices[grant["device_id"]]


def refuse(held, own=(), person=False):
    if person:
        raise HTTPException(403, "no window is shared with you; ask the person to share one")
    lines = ", ".join(sorted({f"«{g['line_name']}»" for g in held}))
    detail = f"; window access is held by line {lines}" if lines else ""
    here = f"; this line's windows: {', '.join(g['id'] + ' ' + g['title'] for g in own)}" if own else ""
    raise HTTPException(403, "no window is shared with this line" + detail + here +
                        "; ask the person to share one with this line")


def require_window(hub, principal, grant_id):
    # Re-check after awaits: revocation, archival or a replacement discards in-flight reads.
    return resolve_window(hub, principal, grant_id)


def window_share_indicators(db, owner_id):
    return [{"conv_id": g["conv_id"], "device_name": g["device_name"], "kind": "window",
             "label": f"window → «{g['line_name']}» (and its sublines): {g['title']}"} for g in
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
            "SELECT g.id FROM screen_line_window_grants g JOIN screen_devices d ON d.id=g.device_id "
            "WHERE g.id=? AND d.owner_id=?", (grant_id, principal.user_id)).fetchone()
        if not row:
            raise HTTPException(404, "window grant not found")
        await hub.window_grants.revoke(grant_id)
        return {"ok": True}

    return router
