"""Durable, one-shot recovery when a task has no structured hand-off or peer.

The reminder is one line, but it is not one line of everything: a weaker
implementer told only "call request_review or blocked(reason)" repeats the
same uncommitted work next turn, because the generic text never mentions the
work. `reminder` reads the line's own workspaces — the fence mirror first, then a
read-only, bounded, cheap dirty check — and names the exact call the state owes.
Any workspace it cannot read falls back to the generic line rather than guessing
at work it never saw.
"""

import asyncio
import os
import subprocess
import time

from fastapi import HTTPException

from .contracts import ConversationsChangedEvent, MessageEvent, MessageResponse
from .orchestrator_notices import handed_to, notify_root, peer, report
from .orchestrator_sha_check import flag
from .orchestrator_reopen import unreopened
from .orchestrator_handles import message_task
from .orchestrator_contracts import MessageTaskIn
from .orchestrator_store import require_task, require_task_or_root, task
from .orchestrator_wait import live as live_wait
from .task_workspaces import anchor, moved, workspaces


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


def working(runtime, att_id):
    """Whether the attachment's harness turn is open: work in flight, not silence."""
    presence = getattr(runtime, 'presence', None)
    return bool(presence is not None and presence.is_working(att_id))


GENERIC = 'This task has no hand-off. Call request_review or blocked(reason).'
STATUS_BOUND = 4096   # bytes of `git status --porcelain` we ever look at
STATUS_TIMEOUT = 10   # seconds one workspace status read may take


def _dirty(path):
    """True when the workspace has changes, False when it is clean, None when unreadable."""
    try:
        done = subprocess.run(['git', '--no-optional-locks', 'status', '--porcelain'],
                              cwd=path, capture_output=True, text=True, timeout=STATUS_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.stdout[:STATUS_BOUND].strip():
        return True
    return False if done.returncode == 0 else None


def _named(path):
    """A repository by the name the implementer uses for it: `/x/y/frontend` -> `frontend`."""
    return os.path.basename(os.path.normpath(path)) or path


def reminder(db, att):
    """What this line's state owes next, or GENERIC when no workspace state could be read."""
    conv_id = att['conv_id']
    try:
        spaces = workspaces(db, conv_id)
        if spaces:
            # The commit check first: a fenced worker commits to its private mirror
            # until accept, so from outside its worktree still reads as modified.
            # Reading the dirty state first told a worker that had already
            # committed to go and commit again — the loop this reminder exists
            # to break.
            committed = moved(db, conv_id)
            if committed:
                repo, sha = _named(committed[0][0]), committed[0][1]
                return (f'This task has no hand-off: {repo} already has a commit beyond the base '
                        f'{sha}: run the gates and call request_review with {sha}; if you have '
                        'further uncommitted edits, commit them first and request review with '
                        'the newer SHA.')
            states = [_dirty(item['path']) for item in spaces]
            if None not in states:
                if True in states:
                    repo = _named(spaces[states.index(True)]['repository'])
                    return (f'This task has no hand-off. You have uncommitted changes in {repo}: '
                            'run the gates, commit with a one-line Conventional Commit and no '
                            'body, then call request_review with the full 40-char SHA.')
                return ('This task has no hand-off and nothing changed in the workspaces: if you '
                        'are blocked call blocked(reason), otherwise continue; if you are waiting '
                        'on a long command call waiting(reason, seconds).')
    except Exception:
        return GENERIC  # an unreadable workspace says nothing about the work
    return GENERIC


async def settle(runtime, att):
    if not candidate(runtime.db, att):
        return
    db = runtime.db
    row = task(db, att['conv_id'])
    if live_wait(row):
        # A declared wait: the implementer is working, not stuck. No reminder,
        # no escalation — the line already says that it is waiting.
        return
    if working(runtime, att['id']):
        # A tool call in flight keeps the harness turn open, so the implementer
        # is busy and a hand-off is not due yet.
        return
    if row['stall_stage'] == 0:
        # What the line owes is read from its workspaces first, off the event loop:
        # git runs are bounded and read-only, and a failed read falls back to GENERIC.
        text = await asyncio.to_thread(reminder, db, att)
        # Persist both the reminder and its identity before any delivery await.
        # Routing can deliver synchronously; restarts must retain the same mail.
        with db.lock, db.conn:
            current = db.conn.execute('SELECT status,stall_stage FROM task_reviews WHERE conv_id=?',
                                      (att['conv_id'],)).fetchone()
            if current['status'] not in ('implementing', 'idle') or current['stall_stage'] != 0:
                return
            body = f"@{att['name']} {text}"
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
        row = task(db, att['conv_id'])
        await report(runtime, row)
        await flag(runtime, row, row['findings'])


def resume(db, conv_id):
    """A structured attempt starts a new progress episode, even if admission fails."""
    db._exec("UPDATE task_reviews SET status='implementing',stall_stage=0,stall_notice_id=NULL,"
             "wait_until=NULL,"
             "report_id=CASE WHEN status='blocked' OR stall_stage=3 THEN NULL ELSE report_id END "
             'WHERE conv_id=?', (conv_id,))


async def blocked(runtime, actor, conv_id, body):
    row = require_task(runtime.db, actor, conv_id)
    if row['status'] not in ('implementing', 'idle', 'blocked'):
        raise HTTPException(409, 'only an implementing task can be blocked')
    runtime.db._exec("UPDATE task_reviews SET status='blocked',findings=?,stall_stage=0,blocked_at=?,"
                     "wait_until=NULL,"
                     "report_id=CASE WHEN stall_stage=3 THEN NULL ELSE report_id END WHERE conv_id=?",
                     (body.reason, time.time(), conv_id))
    row = task(runtime.db, conv_id)
    await report(runtime, row)
    await flag(runtime, row, body.reason)
    handed_to(runtime, row['implementer_id'], row['implementer_id'])
    await runtime.broadcast_all(ConversationsChangedEvent())
    return task(runtime.db, conv_id)


async def resume_work(runtime, actor, conv_id, body):
    """The implementer says it is working again and the root hears why, once; or the root
    captain (or a person) gives a blocked implementer new direction, which clears the block."""
    row, by_root = require_task_or_root(runtime.db, actor, conv_id)
    if row['status'] != 'blocked':
        raise HTTPException(409, 'only a blocked task can resume work')
    if not by_root:
        await _unblock(runtime, row, body.note)
        return task(runtime.db, conv_id)
    if not body.note:
        raise HTTPException(422, 'resume_work from the root captain needs a note: the new direction')
    await message_task(runtime, actor, conv_id, MessageTaskIn(text=body.note))
    await _unblock(runtime, row)
    if actor.attachment_id:
        handed_to(runtime, actor.attachment_id, row['implementer_id'])
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
