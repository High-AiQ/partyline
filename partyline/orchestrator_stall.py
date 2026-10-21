"""Durable, one-shot recovery when a task has no structured hand-off or peer."""

import asyncio
import time

from fastapi import HTTPException

from .contracts import ConversationsChangedEvent, MessageEvent, MessageResponse
from .orchestrator_notices import handed_to, notify_root, peer, report
from .orchestrator_reopen import unreopened
from .orchestrator_store import require_task, task
from .task_workspaces import anchor


def candidate(db, att):
    row = task(db, att['conv_id']) if att else None
    return bool(row and row['implementer_id'] == att['id']
                and row['status'] in ('implementing', 'idle') and row['stall_stage'] in (0, 2)
                and peer(db, att) is None)


def delivered(db, att, messages):
    row = task(db, att['conv_id'])
    if row and row['implementer_id'] == att['id'] and row['stall_stage'] == 1:
        if any(message.get('id') == row['stall_notice_id'] for message in messages):
            db._exec('UPDATE task_reviews SET stall_stage=2 WHERE conv_id=? AND stall_stage=1',
                     (att['conv_id'],))


async def settle(runtime, att):
    if not candidate(runtime.db, att):
        return
    db = runtime.db
    row = task(db, att['conv_id'])
    if row['stall_stage'] == 0:
        # Persist both the reminder and its identity before any delivery await.
        # Routing can deliver synchronously; restarts must retain the same mail.
        with db.lock, db.conn:
            current = db.conn.execute('SELECT status,stall_stage FROM task_reviews WHERE conv_id=?',
                                      (att['conv_id'],)).fetchone()
            if current['status'] not in ('implementing', 'idle') or current['stall_stage'] != 0:
                return
            body = f"@{att['name']} This task has no hand-off. Call request_review or blocked(reason)."
            cursor = db.conn.execute(
                'INSERT INTO messages(conv_id,sender,sender_type,body,created_at,audience_attachment_id) '
                "VALUES(?,'system','system',?,?,?)", (att['conv_id'], body, time.time(), att['id']))
            db.conn.execute('UPDATE task_reviews SET stall_stage=1,stall_notice_id=? WHERE conv_id=?',
                            (cursor.lastrowid, att['conv_id']))
        notice = db.message_by_id(att['conv_id'], cursor.lastrowid)
        await runtime.broadcast(att['conv_id'], MessageEvent(message=MessageResponse.model_validate(notice)))
        await runtime.route_mentions(att['conv_id'], notice, force=True)
    else:
        db._exec("UPDATE task_reviews SET stall_stage=3,findings=? WHERE conv_id=?",
                 ('stalled: implementer returned again without request_review or blocked(reason)',
                  att['conv_id']))
        await report(runtime, task(db, att['conv_id']))


def resume(db, conv_id):
    """A structured attempt starts a new progress episode, even if admission fails."""
    db._exec("UPDATE task_reviews SET status='implementing',stall_stage=0,stall_notice_id=NULL,"
             "report_id=CASE WHEN status='blocked' OR stall_stage=3 THEN NULL ELSE report_id END "
             'WHERE conv_id=?', (conv_id,))


async def blocked(runtime, actor, conv_id, body):
    row = require_task(runtime.db, actor, conv_id)
    if row['status'] not in ('implementing', 'idle', 'blocked'):
        raise HTTPException(409, 'only an implementing task can be blocked')
    runtime.db._exec("UPDATE task_reviews SET status='blocked',findings=?,stall_stage=0,blocked_at=?,"
                     "report_id=CASE WHEN stall_stage=3 THEN NULL ELSE report_id END WHERE conv_id=?",
                     (body.reason, time.time(), conv_id))
    await report(runtime, task(runtime.db, conv_id))
    handed_to(runtime, row['implementer_id'], row['implementer_id'])
    await runtime.broadcast_all(ConversationsChangedEvent())
    return task(runtime.db, conv_id)


async def resume_work(runtime, actor, conv_id, body):
    """The implementer says it is working again; the root hears why, once."""
    row = require_task(runtime.db, actor, conv_id)
    if row['status'] != 'blocked':
        raise HTTPException(409, 'only a blocked task can resume work')
    await _unblock(runtime, row, body.note)
    return task(runtime.db, conv_id)


async def _unblock(runtime, row, note=None):
    resume(runtime.db, row['conv_id'])
    await runtime.broadcast_all(ConversationsChangedEvent())
    if note:
        await notify_root(runtime, row, f'unblocked: {note}')


def directed(db, row, since):
    """A message from the root captain or a person, after `since`, for this implementer."""
    return db._exec(
        'SELECT 1 FROM messages WHERE conv_id=? AND created_at>? '
        'AND (sender_type=\'human\' OR source_conv_id=?) '
        'AND (audience_attachment_id IS NULL OR audience_attachment_id=?) LIMIT 1',
        (row['conv_id'], since or 0, row['root_id'], row['implementer_id'])).fetchone()


async def ended(runtime, att):
    """An implementer that finished its turn with nothing pending is idle, not implementing."""
    db = runtime.db
    row = task(db, att['conv_id'])
    if (row and row['implementer_id'] == att['id'] and row['status'] == 'implementing'
            and not db.queued_delivery_ids(att['id'])):
        await _set_status(runtime, att['conv_id'], 'idle', 'implementing')
    if row and row['implementer_id'] == att['id']:
        await asyncio.to_thread(anchor, db, att['conv_id'])


async def _set_status(runtime, conv_id, new, old):
    moved = runtime.db._exec('UPDATE task_reviews SET status=? WHERE conv_id=? AND status=?',
                             (new, conv_id, old))
    if moved.rowcount == 1:
        await runtime.broadcast_all(ConversationsChangedEvent())


async def began(runtime, att):
    """A blocked implementer starting a turn after fresh word from above is working again."""
    row = task(runtime.db, att['conv_id'])
    if row and row['implementer_id'] == att['id'] and row['status'] == 'idle':
        await _set_status(runtime, att['conv_id'], 'implementing', 'idle')
    if (row and row['implementer_id'] == att['id'] and row['status'] == 'blocked'
            and directed(runtime.db, row, row['blocked_at'])):
        await _unblock(runtime, row)
    await unreopened(runtime, att)
