"""Two-party completion and durable detach recovery for captain handovers."""
import asyncio
import logging
import time

from fastapi import APIRouter, HTTPException, Request

from .auth_guard import request_principal
from .contracts import AttachmentRemovedEvent, MessageEvent, MessageResponse
from .attachment_lifecycle import remove_stopped_record
from .attachment_tmp import attachment_tmp_dir
from .agent_connection import remove_connection
from .line_process_routes import detach_attachment
from .message_queries import as_message

CONFIRM_TIMEOUT_SECONDS = 30 * 60
MAINTENANCE_INTERVAL_SECONDS = 30
logger = logging.getLogger(__name__)


def _insert_notice(conn, conv_id, body, now):
    cur = conn.execute("INSERT INTO messages(conv_id,sender,sender_type,body,created_at) "
                       "VALUES(?,'system','system',?,?)", (conv_id, body, now))
    return as_message(dict(id=cur.lastrowid, conv_id=conv_id, sender='system', sender_type='system',
                           body=body, created_at=now))


def confirm(db, conv, att_id, ident, now=None, *, jobs=(), live_jobs=None):
    """Record the caller's confirmation and atomically create a detach intent."""
    now = time.time() if now is None else now
    with db.lock:
        try:
            db.conn.execute('BEGIN IMMEDIATE')
            row = db.conn.execute('SELECT * FROM captain_handovers WHERE id=? AND conv_id=?',
                                  (ident, conv)).fetchone()
            if not row:
                raise HTTPException(404, 'Handover not found on this line')
            if att_id not in (row['from_attachment_id'], row['to_attachment_id']):
                raise HTTPException(403, 'Only the two handover participants may confirm')
            if row['state'] == 'completed':
                db.conn.commit()
                return dict(row), None
            if row['state'] != 'accepted':
                raise HTTPException(409, 'Only an accepted handover may be completed')
            from .handover_jobs import jobs_text
            if jobs and live_jobs != 'transfer':
                raise HTTPException(409, jobs_text(jobs) +
                    '\nFinish or kill each job, or explicitly acknowledge with live_jobs="transfer".')
            column = 'from_done' if att_id == row['from_attachment_id'] else 'to_done'
            db.conn.execute(f'UPDATE captain_handovers SET {column}=1 WHERE id=?', (ident,))
            current = db.conn.execute('SELECT * FROM captain_handovers WHERE id=?', (ident,)).fetchone()
            notice = None
            if current['from_done'] and current['to_done']:
                db.conn.execute("UPDATE captain_handovers SET state='completed',completed_at=? WHERE id=?",
                                (now, ident))
                old = db.conn.execute('SELECT name FROM attachments WHERE id=?',
                                      (current['from_attachment_id'],)).fetchone()
                new = db.conn.execute('SELECT name FROM attachments WHERE id=?',
                                      (current['to_attachment_id'],)).fetchone()
                transfer = ''
                if jobs:
                    path = attachment_tmp_dir(current['from_attachment_id'])
                    transfer = (jobs_text(jobs) + f'\nFiles retained for this line at {path}; '
                                'Successor TMPDIR/retained links to this path where supported. '
                                'Detach still stops the original process group; transfer preserves files.')
                notice = _insert_notice(db.conn, conv,
                    f"☏ Captain handover {ident} completed by {old['name'] if old else 'old captain'} "
                    f"and {new['name'] if new else 'new captain'}; detaching the old captain."
                    + transfer, now)
                current = db.conn.execute('SELECT * FROM captain_handovers WHERE id=?', (ident,)).fetchone()
            db.conn.commit()
            return dict(current), notice
        except BaseException:
            db.conn.rollback()
            raise


def timeout_notices(db, now=None):
    """Persist a single notice and marker together; a crash cannot duplicate it."""
    now = time.time() if now is None else now
    messages = []
    with db.lock:
        try:
            db.conn.execute('BEGIN IMMEDIATE')
            rows = db.conn.execute("SELECT h.*,a.name AS old_name,b.name AS new_name "
                "FROM captain_handovers h LEFT JOIN attachments a ON a.id=h.from_attachment_id "
                "LEFT JOIN attachments b ON b.id=h.to_attachment_id "
                "WHERE h.state='accepted' AND h.timeout_notified_at IS NULL AND h.accepted_at<=?",
                (now - CONFIRM_TIMEOUT_SECONDS,)).fetchall()
            for row in rows:
                missing = []
                if not row['from_done']:
                    missing.append(row['old_name'] or 'old captain')
                if not row['to_done']:
                    missing.append(row['new_name'] or 'new captain')
                text = (f"☏ Captain handover {row['id']} timed out; waiting for "
                        f"{', '.join(missing)} to confirm. The old captain remains attached; "
                        "a person can resolve this handover.")
                messages.append(_insert_notice(db.conn, row['conv_id'], text, now))
                db.conn.execute('UPDATE captain_handovers SET timeout_notified_at=? WHERE id=?',
                                (now, row['id']))
            db.conn.commit()
            return messages
        except BaseException:
            db.conn.rollback()
            raise


def resolve_timeout(db, conv, ident, now=None):
    """A person releases the stale slot without impersonating either confirmer."""
    now = time.time() if now is None else now
    with db.lock, db.conn:
        db.conn.execute('BEGIN IMMEDIATE')
        row = db.conn.execute('SELECT * FROM captain_handovers WHERE id=? AND conv_id=?',
                              (ident, conv)).fetchone()
        if not row or row['state'] != 'accepted' or row['timeout_notified_at'] is None:
            raise HTTPException(409, 'Only a timed-out accepted handover may be resolved')
        db.conn.execute("UPDATE captain_handovers SET state='cancelled',cancelled_at=? WHERE id=?",
                        (now, ident))
        return _insert_notice(db.conn, conv, f"☏ A person resolved timed-out handover {ident}; "
                              "the old captain was not detached by this action.", now)


def pending_detaches(db):
    return [dict(row) for row in db._exec("SELECT * FROM captain_handovers WHERE state='completed' "
                                         "AND detach_finished_at IS NULL ORDER BY completed_at").fetchall()]


async def finish_detach(runtime, row):
    """Run the existing PTY teardown; retain the intent until it succeeds."""
    locks = getattr(runtime, 'handover_detach_locks', None)
    if locks is None:
        locks = runtime.handover_detach_locks = {}
    async with locks.setdefault(row['id'], asyncio.Lock()):
        current = runtime.db._exec('SELECT * FROM captain_handovers WHERE id=?', (row['id'],)).fetchone()
        if not current or current['state'] != 'completed' or current['detach_finished_at'] is not None:
            return
        att_id = current['from_attachment_id']
        att = runtime.db.get_attachment(att_id)
        if att and att.get('is_lead'):
            raise HTTPException(409, 'old attachment is now a captain; detach requires human resolution')
        from .handover_temp import prepare, reap_notice
        await asyncio.to_thread(prepare, runtime, dict(current))
        if att and (att['status'] != 'detached' or att_id in runtime.live):
            await detach_attachment(runtime, att_id)
        await remove_stopped_record(runtime.db, att_id, missing_ok=True)
        text = await asyncio.to_thread(reap_notice, dict(current))
        if text is not None:
            with runtime.db.lock, runtime.db.conn:
                exists = runtime.db.conn.execute(
                    'SELECT 1 FROM messages WHERE conv_id=? AND body=?',
                    (current['conv_id'], text)).fetchone()
                notice = None if exists else _insert_notice(
                    runtime.db.conn, current['conv_id'], text, time.time())
            if notice:
                await runtime.broadcast(current['conv_id'],
                                        MessageEvent(message=MessageResponse.model_validate(notice)))
                if hasattr(runtime, 'route_mentions'):
                    await runtime.route_mentions(current['conv_id'],
                        {**notice, 'audience_attachment_id': current['to_attachment_id']}, force=True)
        remove_connection(runtime.db.path, att_id)
        getattr(runtime, "handover_job_cache", {}).pop(att_id, None)
        getattr(runtime, "uncredited", {}).pop(att_id, None)
        getattr(runtime, "unclaimed_noticed", set()).discard(att_id)
        getattr(runtime, "reattaching", set()).discard(att_id)
        try:
            await runtime.broadcast(current["conv_id"], AttachmentRemovedEvent(
                attachment_id=att_id, conversation_id=current["conv_id"]))
        except Exception:
            logger.exception("could not broadcast removal of %s", att_id)
        runtime.db._exec("UPDATE captain_handovers SET detach_finished_at=? WHERE id=? "
                         "AND state='completed' AND detach_finished_at IS NULL", (time.time(), row['id']))


async def _try_detach(runtime, row):
    try:
        await finish_detach(runtime, row)
    except Exception:
        logger.exception('handover detach failed for %s; it will be retried', row['id'])


async def maintenance_once(runtime):
    from .tmp_retention import reap_pending
    await asyncio.to_thread(reap_pending, set(runtime.live))
    for message in timeout_notices(runtime.db):
        try:
            await runtime.broadcast(message['conv_id'],
                                    MessageEvent(message=MessageResponse.model_validate(message)))
        except Exception:
            logger.exception('could not broadcast handover timeout notice %s', message['id'])
    for row in pending_detaches(runtime.db):
        await _try_detach(runtime, row)


async def maintenance(runtime):
    while True:
        try:
            await maintenance_once(runtime)
        except Exception:
            logger.exception('handover maintenance failed; it will be retried')
        await asyncio.sleep(MAINTENANCE_INTERVAL_SECONDS)


async def complete_route(runtime, request: Request, conv: str, body):
    from .captain_handover import _locks, _principal
    actor = _principal(request, conv)
    row = runtime.db._exec('SELECT * FROM captain_handovers '
                           'WHERE id=? AND conv_id=?', (body.handover_id, conv)).fetchone()
    ids = [actor.attachment_id] + ([row['from_attachment_id'], row['to_attachment_id']] if row else [])
    jobs = []
    if (row and row['state'] == 'accepted'
            and actor.attachment_id in (row['from_attachment_id'], row['to_attachment_id'])):
        from .handover_jobs import inspect_completion
        jobs = await asyncio.to_thread(inspect_completion, runtime, row['from_attachment_id'])
    current, notice = await _locks(runtime, ids, lambda: confirm(runtime.db, conv, actor.attachment_id,
                                                                 body.handover_id, jobs=jobs,
                                                                 live_jobs=body.live_jobs))
    if notice:
        if jobs:
            from .tmp_retention import remember
            await asyncio.to_thread(remember, current['from_attachment_id'], conv,
                                    current['to_attachment_id'], jobs)
        await runtime.broadcast(conv, MessageEvent(message=MessageResponse.model_validate(notice)))
        if hasattr(runtime, 'route_mentions'):
            await runtime.route_mentions(conv,
                {**notice, 'audience_attachment_id': current['to_attachment_id']}, force=True)
    # Schedule teardown after returning control; the persisted intent survives a crash.
    if current['state'] == 'completed' and current['detach_finished_at'] is None:
        asyncio.create_task(_try_detach(runtime, current))
    return {'handover_id': body.handover_id, 'state': current['state'],
            'from_done': bool(current['from_done']), 'to_done': bool(current['to_done'])}


async def resolve_route(runtime, request: Request, conv: str, body):
    actor = request_principal(request)
    if actor.kind != 'user':
        raise HTTPException(403, 'Only a person may resolve a timed-out handover')
    notice = resolve_timeout(runtime.db, conv, body.handover_id)
    await runtime.broadcast(conv, MessageEvent(message=MessageResponse.model_validate(notice)))
    return {'handover_id': body.handover_id, 'state': 'cancelled'}


def router_for(runtime):
    from .captain_handover import CompleteIn, HandoverIdIn
    router = APIRouter()

    @router.post('/api/conversations/{conv}/handover/complete')
    async def complete(request: Request, conv: str, body: CompleteIn):
        return await complete_route(runtime, request, conv, body)

    @router.post('/api/conversations/{conv}/handover/resolve')
    async def resolve(request: Request, conv: str, body: HandoverIdIn):
        return await resolve_route(runtime, request, conv, body)

    return router


def ensure_handover_detached(db, att_id):
    pending = db._exec("SELECT 1 FROM captain_handovers WHERE from_attachment_id=? "
                       "AND state='completed' AND detach_finished_at IS NULL", (att_id,)).fetchone()
    if pending:
        raise HTTPException(409, "completed captain handover is still detaching this attachment")
