"""Durable, one-shot recovery when a task has no structured hand-off or peer."""

import time

from fastapi import HTTPException

from .contracts import ConversationsChangedEvent, MessageEvent, MessageResponse
from .orchestrator_notices import handed_to, peer, report
from .orchestrator_store import require_task, task


def candidate(db, att):
    row = task(db, att['conv_id']) if att else None
    return bool(row and row['implementer_id'] == att['id']
                and row['status'] == 'implementing' and row['stall_stage'] in (0, 2)
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
            if current['status'] != 'implementing' or current['stall_stage'] != 0:
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
    if row['status'] not in ('implementing', 'blocked'):
        raise HTTPException(409, 'only an implementing task can be blocked')
    runtime.db._exec("UPDATE task_reviews SET status='blocked',findings=?,stall_stage=0,"
                     "report_id=CASE WHEN stall_stage=3 THEN NULL ELSE report_id END WHERE conv_id=?",
                     (body.reason, conv_id))
    await report(runtime, task(runtime.db, conv_id))
    handed_to(runtime, row['implementer_id'], row['implementer_id'])
    await runtime.broadcast_all(ConversationsChangedEvent())
    return task(runtime.db, conv_id)
