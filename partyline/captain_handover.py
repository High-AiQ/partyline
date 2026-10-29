"""Durable captain handover offers and atomic acceptance."""
import asyncio
import math
import time
import uuid

from fastapi import HTTPException, Request
from pydantic import BaseModel

from .auth_guard import request_principal
from .bridge_pack import pack_for
from .contracts import MessageEvent, MessageResponse
from .mention_relay import post_private, ring_workers
from .message_queries import as_message
from .role_delivery import _instructions, current_role

MIN_ATTACHMENT_SECONDS = 60
OFFER_TTL_SECONDS = 15 * 60
MAX_DEBRIEF = 4000
HINT = ("Reference files, directories, notes, worktrees and report IDs "
        "instead of explaining everything inline.")


class OfferIn(BaseModel):
    attachment_id: str
    debrief: str = ""


class HandoverIdIn(BaseModel):
    handover_id: str


def _expire(conn, conv_id, now):
    conn.execute("UPDATE captain_handovers SET state='expired',expired_at=? "
                 "WHERE conv_id=? AND state='offered' AND offered_at<=?",
                 (now, conv_id, now - OFFER_TTL_SECONDS))


def _validate(conn, conv_id, old_id, target_id, live, pending, now):
    old = conn.execute("SELECT * FROM attachments WHERE id=? AND conv_id=? AND is_lead=1",
                       (old_id, conv_id)).fetchone()
    if not old or old['status'] != 'running' or old_id not in live:
        raise HTTPException(403, "Only the current live captain may hand over")
    line = conn.execute("SELECT archived_at FROM conversations WHERE id=?", (conv_id,)).fetchone()
    if not line or line['archived_at'] is not None:
        raise HTTPException(409, "Line is archived or missing")
    if old_id == target_id:
        raise HTTPException(400, "Cannot hand captainship to yourself")
    target = conn.execute("SELECT * FROM attachments WHERE id=?", (target_id,)).fetchone()
    if not target or target['conv_id'] != conv_id:
        raise HTTPException(404, "Target attachment must be on this same line")
    if target['status'] != 'running' or target_id not in live:
        raise HTTPException(409, "Target attachment must be currently attached and live")
    if conn.execute("SELECT 1 FROM captain_handovers WHERE state='completed' AND detach_finished_at IS NULL "
                    "AND from_attachment_id IN (?,?)", (old_id, target_id)).fetchone():
        raise HTTPException(409, 'A participant has an unfinished handover detach')
    remaining = math.ceil(MIN_ATTACHMENT_SECONDS - (now - target['created_at']))
    if remaining > 0:
        raise HTTPException(409, f"Target must be attached for 60 seconds; {remaining} seconds remain")
    if pending and pending.requester_attachment_id == old_id:
        raise HTTPException(409, "Resolve or cancel your pending restart request first")
    return old, target


def _message(conn, conv, body, now, audience=None):
    cur = conn.execute("INSERT INTO messages(conv_id,sender,sender_type,body,created_at,"
                       "audience_attachment_id) "
                       "VALUES(?,'system','system',?,?,?)", (conv, body, now, audience))
    return as_message(dict(id=cur.lastrowid, conv_id=conv, sender='system', sender_type='system',
                           body=body, created_at=now, audience_attachment_id=audience))


def offer(db, conv, old, target, debrief, live, pending=None, now=None):
    if not debrief.strip():
        raise HTTPException(400, f"A debrief is required. {HINT}")
    if len(debrief) > MAX_DEBRIEF:
        raise HTTPException(400, f"Debrief is {len(debrief)} characters; maximum {MAX_DEBRIEF}. {HINT}")
    now = time.time() if now is None else now
    with db.lock:
        _expire(db.conn, conv, now)
        db.conn.commit()
        try:
            db.conn.execute('BEGIN IMMEDIATE')
            previous, _ = _validate(db.conn, conv, old, target, live, pending, now)
            if db.conn.execute("SELECT 1 FROM captain_handovers WHERE conv_id=? "
                               "AND state IN ('offered','accepted')", (conv,)).fetchone():
                raise HTTPException(409, 'A handover is already pending on this line')
            ident = uuid.uuid4().hex
            db.conn.execute("INSERT INTO captain_handovers(id,conv_id,from_attachment_id,to_attachment_id,"
                            "debrief,state,offered_at) VALUES(?,?,?,?,?,'offered',?)",
                            (ident, conv, old, target, debrief, now))
            msg = _message(db.conn, conv, f"☏ Captain handover offer {ident} from @{previous['name']}:\n\n"
                           f"{debrief}\n\nAccept with accept_handover({ident}).", now, target)
            db.conn.commit()
            return ident, msg
        except BaseException:
            db.conn.rollback()
            raise


def cancel(db, conv, caller, ident, now=None):
    now = time.time() if now is None else now
    with db.lock:
        _expire(db.conn, conv, now)
        db.conn.commit()
        with db.conn:
            db.conn.execute("BEGIN IMMEDIATE")
            row = db.conn.execute("SELECT * FROM captain_handovers WHERE id=? AND conv_id=?",
                                  (ident, conv)).fetchone()
            if not row or row['state'] != 'offered':
                raise HTTPException(409, 'Handover is not an active offer')
            if row['from_attachment_id'] != caller or not db.conn.execute(
                "SELECT 1 FROM attachments WHERE id=? AND conv_id=? AND is_lead=1",
                (caller, conv)).fetchone():
                raise HTTPException(403, 'Only the offering captain may cancel')
            db.conn.execute("UPDATE captain_handovers SET state='cancelled',cancelled_at=? WHERE id=?",
                            (now, ident))


def accept(db, conv, caller, ident, live, pending=None, now=None):
    now = time.time() if now is None else now
    with db.lock:
        _expire(db.conn, conv, now)
        db.conn.commit()
        try:
            db.conn.execute('BEGIN IMMEDIATE')
            row = db.conn.execute("SELECT * FROM captain_handovers WHERE id=? AND conv_id=?",
                              (ident, conv)).fetchone()
            if not row or row['state'] != 'offered':
                raise HTTPException(409, 'Handover is not an active offer')
            if row['to_attachment_id'] != caller:
                raise HTTPException(403, 'Only the offered attachment may accept')
            old, target = _validate(db.conn, conv, row['from_attachment_id'], caller, live, pending, now)
            db.conn.execute("UPDATE attachments SET is_lead=0 WHERE id=?", (old['id'],))
            db.conn.execute("UPDATE attachments SET is_lead=1 WHERE id=?", (caller,))
            for side in ('a', 'b'):
                db.conn.execute(f"UPDATE line_bridges SET {side}_attachment_id=? WHERE {side}_conv_id=? "
                                f"AND {side}_attachment_id=? AND closed_at IS NULL",
                                (caller, conv, old['id']))
            db.conn.execute("UPDATE lead_heartbeat SET attachment_id=?,generation=generation+1,"
                            "pending_message_id=NULL,pending_since_id=NULL "
                            "WHERE conv_id=? AND attachment_id=?",
                            (caller, conv, old['id']))
            db.conn.execute("UPDATE conversation_write_grant_requests SET requester_attachment_id=? "
                            "WHERE requester_attachment_id=?", (caller, old['id']))
            db.conn.execute("UPDATE memory_limit_requests SET requester_attachment_id=? "
                            "WHERE requester_attachment_id=? AND expired_at IS NULL", (caller, old['id']))
            db.conn.execute("UPDATE captain_handovers SET state='accepted',accepted_at=? WHERE id=?",
                            (now, ident))
            msg = _message(db.conn, conv, f"☏ {old['name']} handed captainship to {target['name']}; "
                           "the old captain remains attached while handing off.", now)
            db.conn.commit()
            return dict(old), dict(target), msg
        except BaseException:
            db.conn.rollback()
            raise


def state_text(db, att_id):
    if not hasattr(db, '_exec'):
        return ''
    row = db._exec("SELECT * FROM captain_handovers WHERE state IN ('offered','accepted') "
                   "AND (from_attachment_id=? OR to_attachment_id=?) ORDER BY offered_at DESC LIMIT 1",
                   (att_id, att_id)).fetchone()
    if not row or (row['state'] == 'offered' and row['offered_at'] + OFFER_TTL_SECONDS <= time.time()):
        return ''
    if row['state'] == 'accepted':
        remaining = []
        if not row['from_done']:
            remaining.append('old captain')
        if not row['to_done']:
            remaining.append('new captain')
        role = "you are handing off" if row['from_attachment_id'] == att_id else "you are the receiver"
        return (f"Captain handover {row['id']}: accepted; {role}; "
                f"awaiting {', '.join(remaining)}. "
                "Both participants call complete_handover with this id.")
    return (f"Captain handover {row['id']}: offered; "
            f"{'you are handing off' if row['from_attachment_id'] == att_id else 'you are the receiver'}.")


def _principal(request, conv):
    actor = request_principal(request)
    if actor.kind != 'machine' or actor.conv_id != conv:
        raise HTTPException(403, 'Only an attachment on this line may use handover')
    return actor


async def _locks(runtime, ids, operation):
    locks = [runtime.resume_locks.setdefault(i, asyncio.Lock()) for i in sorted(set(ids))]
    acquired = []
    try:
        for lock in locks:
            await lock.acquire()
            acquired.append(lock)
        async with runtime.db._runtime_serialized_async():
            return operation()
    finally:
        for lock in reversed(acquired):
            lock.release()


def _live_ids(runtime, ids):
    """Only adapters still owning their database activation count as live."""
    found = set()
    for ident in ids:
        adapter = runtime.live.get(ident)
        att = runtime.db.get_attachment(ident)
        if adapter is not None and att and runtime.activation_matches(adapter, att):
            found.add(ident)
    return found


async def offer_route(runtime, request: Request, conv: str, body: OfferIn):
    actor = _principal(request, conv)
    ident, msg = await _locks(runtime, [actor.attachment_id, body.attachment_id], lambda: offer(
        runtime.db, conv, actor.attachment_id, body.attachment_id, body.debrief,
        _live_ids(runtime, [actor.attachment_id, body.attachment_id]),
        getattr(runtime, 'restart_request', None)))
    await runtime.route_mentions(conv, {**msg, 'body': ''}, force=True)
    return {'handover_id': ident, 'state': 'offered'}


async def cancel_route(runtime, request: Request, conv: str, body: HandoverIdIn):
    actor = _principal(request, conv)
    await _locks(runtime, [actor.attachment_id], lambda: cancel(runtime.db, conv, actor.attachment_id,
                                                                 body.handover_id))
    return {'handover_id': body.handover_id, 'state': 'cancelled'}


async def accept_route(runtime, request: Request, conv: str, body: HandoverIdIn):
    actor = _principal(request, conv)
    row = runtime.db._exec('SELECT from_attachment_id FROM captain_handovers WHERE id=? AND conv_id=?',
                           (body.handover_id, conv)).fetchone()
    ids = [actor.attachment_id] + ([row['from_attachment_id']] if row else [])
    old, target, msg = await _locks(runtime, ids, lambda: accept(runtime.db, conv, actor.attachment_id,
        body.handover_id, _live_ids(runtime, ids), getattr(runtime, 'restart_request', None)))
    await runtime.broadcast(conv, MessageEvent(message=MessageResponse.model_validate(msg)))
    pack = _instructions(current_role(runtime.db, target['id']), runtime.db)
    private = await post_private(runtime, conv, 'system', 'system',
                       f"☏ You accepted captainship from {old['name']}.\n\n{pack}\n\n"
                       f"{pack_for(runtime.db, target['id'])}", audience=target['id'], route=False)
    await runtime.route_mentions(conv, {**private, 'body': ''}, force=True)
    await post_private(runtime, conv, 'system', 'system',
                       f"☏ You handed captainship to {target['name']}; "
                       "you remain attached while handing off.",
                       audience=old['id'])
    await ring_workers(runtime, conv, runtime.db.get_attachment(target['id']))
    return {'handover_id': body.handover_id, 'state': 'accepted'}


async def expire_offers(runtime):
    """Expire persisted offers after restart and while the server is running."""
    while True:
        now = time.time()
        runtime.db._exec("UPDATE captain_handovers SET state='expired',expired_at=? "
                         "WHERE state='offered' AND offered_at<=?", (now, now - OFFER_TTL_SECONDS))
        await asyncio.sleep(30)
