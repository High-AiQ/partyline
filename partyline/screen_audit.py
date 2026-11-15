"""Durable append-only control audit with transactional message publication."""

import hashlib
import json
import time

from .message_queries import as_message


def record(db, share_id, conv_id, agent, entry):
    with db.lock:
        try:
            previous = db.conn.execute(
                "SELECT entry_hash FROM screen_control_audit WHERE share_id=? ORDER BY id DESC LIMIT 1",
                (share_id,),
            ).fetchone()
            prior = previous[0] if previous else ""
            payload = json.dumps([share_id, conv_id, agent, entry, prior], ensure_ascii=False,
                                 separators=(",", ":"))
            digest = hashlib.sha256(payload.encode()).hexdigest()
            db.conn.execute(
                "INSERT INTO screen_control_audit(share_id,conv_id,agent,entry,previous_hash,entry_hash,"
                "created_at) VALUES(?,?,?,?,?,?,?)",
                (share_id, conv_id, agent, entry, prior, digest, time.time()))
            db.conn.commit()
        except BaseException:
            db.conn.rollback()
            raise


def _body(rows):
    entries = []
    for row in rows:
        agent, entry = row["agent"], row["entry"]
        if (entries and entries[-1][0] == agent and entries[-1][1].startswith("move (")
                and entries[-1][1].endswith(")") and entries[-1][1].count("(") == 1
                and entry.startswith("move (") and entry.endswith(")") and entry.count("(") == 1):
            entries[-1][1], entries[-1][2] = entry, entries[-1][2] + 1
        else:
            entries.append([agent, entry, 1])
    lines, actor = [], None
    for agent, entry, count in entries:
        text = f"{entry} ×{count}" if count > 1 else entry
        lines.append(f"{agent}: {text}" if agent != actor else text)
        actor = agent
    label = ("Window access audit" if rows[0]["share_id"].startswith("window-access:")
             else "Agent control audit")
    return label + " — " + " · ".join(lines) + f" [audit sha256: {rows[-1]['entry_hash']}]"


def publish(db, share_id):
    """Insert the system note and mark its entries together, or leave all pending."""
    if share_id.startswith("window-access:"):
        return None
    with db.lock:
        try:
            rows = db.conn.execute(
                "SELECT * FROM screen_control_audit WHERE share_id=? AND message_id IS NULL ORDER BY id",
                (share_id,),
            ).fetchall()
            if not rows:
                return None
            body, conv_id, now = _body(rows), rows[0]["conv_id"], time.time()
            cursor = db.conn.execute(
                "INSERT INTO messages(conv_id,sender,sender_type,body,created_at) VALUES(?,?,?,?,?)",
                (conv_id, "system", "system", body, now))
            message_id = cursor.lastrowid
            db.conn.execute("UPDATE screen_control_audit SET message_id=? WHERE share_id=? "
                            "AND message_id IS NULL", (message_id, share_id))
            db.conn.commit()
            row = db.conn.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
            return as_message(row)
        except BaseException:
            db.conn.rollback()
            raise


def recover(db):
    """Publish pixel-control batches, never standing window-access entries."""
    shares = db._exec("SELECT DISTINCT share_id FROM screen_control_audit WHERE message_id IS NULL "
                      "AND share_id NOT LIKE 'window-access:%'")
    for row in shares.fetchall():
        publish(db, row["share_id"])


def reset_window_access_notices(runtime, device_id):
    """Let a revoked and re-granted device produce one new first-use notice."""
    notices = getattr(runtime, "window_access_notices", set())
    for key in list(notices):
        if key[1] == device_id:
            notices.discard(key)


async def _note_first_use(runtime, conv_id, device):
    from .contracts import MessageEvent, MessageResponse

    notices = getattr(runtime, "window_access_notices", None)
    if notices is None:
        notices = runtime.window_access_notices = set()
    key = (conv_id, device["id"])
    if key in notices:
        return
    notices.add(key)
    computer = " ".join(str(device.get("name", "")).split()) or "this computer"
    body = f"Agents on this line are using window access on {computer}; log: Settings → Computers"
    try:
        message = runtime.db.add_message(conv_id, "system", "system", body)
    except BaseException:
        notices.discard(key)
        raise
    await runtime.broadcast(conv_id, MessageEvent(message=MessageResponse.model_validate(message)))


async def record_window_access(runtime, conv_id, agent, call, app, title, result, device=None):
    """Persist metadata-only standing window calls without per-call chat messages."""
    share_id = "window-access:" + conv_id
    record(runtime.db, share_id, conv_id, agent,
           f"{call}: {app[:128]} — {title[:256]} ({result[:80]})")
    if device is not None:
        await _note_first_use(runtime, conv_id, device)


async def record_standing_window_access(runtime, hub, principal, conv_id, call, window, device_name, result):
    """Resolve audit labels without allowing a missing grant to skip the audit."""
    from fastapi import HTTPException
    from .screen_grants import resolve_window

    app = title = ""
    device = None
    try:
        grant, connected = resolve_window(hub, principal, window, device_name)
        app, title = grant.get("process", ""), grant.get("title", "")
        device = connected if grant.get("standing_access") else None
    except HTTPException:
        result = "denied"
    await record_window_access(runtime, conv_id, principal.name, call, app, title, result, device)
