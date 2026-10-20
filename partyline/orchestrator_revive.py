"""Bring a task's dead reviewer back; reused by re-entry, the manual action and exit recovery.

Recovery is event driven: a reviewer that exits while its task is in review is
restarted once, and a second failure reports to the root instead of looping.
There is no polling, timer or watchdog.
"""

import asyncio
import logging

from fastapi import HTTPException

from . import reports
from .orchestrator_notices import tell
from .orchestrator_staff import ensure_reviewer
from .orchestrator_store import attachment_task, require_root, task

logger = logging.getLogger(__name__)
LIVE_STATUSES = ('starting', 'running')
_pending: set = set()


def task_lock(runtime, conv_id):
    locks = getattr(runtime, 'task_review_locks', None)
    if locks is None:
        runtime.task_review_locks = locks = {}
    return locks.setdefault(conv_id, asyncio.Lock())


def staffed_by_preset(row):
    return bool(row) and row['policy'] not in ('none', 'captain')


def reviewer_is_live(db, row):
    att = db.get_attachment(row['reviewer_id']) if row['reviewer_id'] else None
    return bool(att) and att['status'] in LIVE_STATUSES


async def brief_reviewer(runtime, row, reviewer):
    note = (f" Your session may be new; round {row['round']} follows changes requested earlier: "
            f"{row['findings']}" if row['round'] > 1 and row['findings'] else '')
    await tell(runtime, reviewer['id'],
               f"Review round {row['round']} at exact SHA {row['sha']} in "
               f"{row['review_worktree']}. {row['what']} — {row['location']}. "
               'Call review_verdict(approve|changes, findings). Never push or implement. '
               'Your approval is acceptance; the root captain merges.' + note,
               source=(row['implementer_id'], row['conv_id']))


async def revive_reviewer(runtime, row):
    """Restart the reviewer of an in-review task and resend its round brief."""
    reviewer = await ensure_reviewer(runtime, row)
    await brief_reviewer(runtime, row, reviewer)
    return reviewer


async def restart_reviewer(runtime, actor, conv_id):
    """The person or root-captain action; replaces attaching to a task line."""
    db = runtime.db
    row = task(db, conv_id)
    if row is None:
        raise HTTPException(404, 'task not found')
    require_root(db, actor, row['root_id'])
    async with task_lock(runtime, conv_id):
        row = task(db, conv_id)
        if row['status'] != 'in_review' or not staffed_by_preset(row):
            raise HTTPException(409, 'only a task in review with a reviewer preset has a reviewer to restart')
        if reviewer_is_live(db, row):
            raise HTTPException(409, 'the reviewer is already running')
        db._exec('UPDATE task_reviews SET reviewer_restarts=0 WHERE conv_id=?', (conv_id,))
        await revive_reviewer(runtime, row)
    return task(db, conv_id)


async def reviewer_exited(runtime, att_id):
    """Exit event: retry once, then report. Never loops."""
    db = runtime.db
    row = attachment_task(db, att_id)
    if (not row or row['reviewer_id'] != att_id or row['status'] != 'in_review'
            or not staffed_by_preset(row)):
        return
    async with task_lock(runtime, row['conv_id']):
        row = task(db, row['conv_id'])
        att = db.get_attachment(att_id)
        if (row['status'] != 'in_review' or att is None or att['status'] != 'exited'
                or row['reviewer_restarts'] >= 2):
            return
        failure = None
        if row['reviewer_restarts'] == 0:
            db._exec('UPDATE task_reviews SET reviewer_restarts=1 WHERE conv_id=?', (row['conv_id'],))
            try:
                await revive_reviewer(runtime, row)
                return
            except (HTTPException, ValueError) as exc:
                failure = getattr(exc, 'detail', str(exc))
        db._exec('UPDATE task_reviews SET reviewer_restarts=2 WHERE conv_id=?', (row['conv_id'],))
        text = (f"Task {row['conv_id']}: the reviewer stopped again during round {row['round']}"
                + (f" ({failure})" if failure else '')
                + '; restart it from the task line header or with restart_reviewer.')
        record, _wake = reports.add(db, row['root_id'], row['conv_id'], 'task server', text, notify=True)
        from .mention_relay import live_manager
        captain = live_manager(runtime, row['root_id'])
        if captain is not None:
            await tell(runtime, captain['id'], f"needs attention: report {record['id']}")


def on_status(runtime, att_id, value):
    """Called from the status callback; schedules recovery without blocking the exit path."""
    db = getattr(runtime, 'db', None)
    if value != 'exited' or getattr(runtime, 'stopping', False):
        return  # a shutdown's exits are reattached by the restart plan, not retried here
    if not hasattr(db, '_exec') or not attachment_task(db, att_id):
        return
    job = asyncio.get_running_loop().create_task(_guarded(runtime, att_id))
    _pending.add(job)
    job.add_done_callback(_pending.discard)


async def _guarded(runtime, att_id):
    try:
        await reviewer_exited(runtime, att_id)
    except Exception:
        logger.exception('reviewer recovery failed for %s', att_id)
