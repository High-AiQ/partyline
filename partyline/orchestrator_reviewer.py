"""Reviewer progress reports and an implementer's fixed, once-per-round nudge."""

from fastapi import HTTPException

from . import reports
from .orchestrator_notices import notify_root, tell, wake_root
from .orchestrator_revive import task_lock
from .orchestrator_store import require_task, task
from .orchestrator_wait import live as live_wait

NUDGE = ('Your implementer asks you to continue this review and submit review_verdict '
         '(or env_gap if you are blocked).')
STALL = 'stalled: reviewer returned without review_verdict or env_gap'


def candidate(row, att):
    return bool(row and row['status'] == 'in_review' and row['reviewer_id'] == att['id']
                and row['reviewer_stall_report_id'] is None and not row['reviewer_env_gap'])


async def settle(runtime, att, review=None):
    from .orchestrator_stall import working

    db = runtime.db
    async with task_lock(runtime, att['conv_id']):
        row = task(db, att['conv_id'])
        if review and (row['round'], row['sha']) != (review['round'], review['sha']):
            return
        if not candidate(row, att) or live_wait(row) or working(runtime, att['id']):
            return
        record, wake = reports.add(db, row['root_id'], row['conv_id'], 'task server',
                                   f"Task {row['conv_id']}, round {row['round']}: {STALL}", notify=True)
        db._exec('UPDATE task_reviews SET reviewer_stall_report_id=? WHERE conv_id=?',
                 (record['id'], row['conv_id']))
    await wake_root(runtime, row, record, wake)


async def nudge_reviewer(runtime, actor, conv_id):
    db = runtime.db
    async with task_lock(runtime, conv_id):
        row = require_task(db, actor, conv_id)
        if row['status'] != 'in_review':
            raise HTTPException(409, 'only a task in review can nudge its reviewer')
        att = db.get_attachment(row['reviewer_id']) if row['reviewer_id'] else None
        adapter = runtime.live.get(att['id']) if att else None
        if (not att or att['status'] != 'running' or adapter is None
                or not runtime.activation_matches(adapter, att)):
            raise HTTPException(409, 'reviewer is not live; ask the root captain to use restart_reviewer')
        if row['reviewer_nudged']:
            raise HTTPException(409, 'reviewer has already been nudged this round; ask the root captain')
        # The private message is durable before delivery; claim before the await
        # so concurrent calls and failed delivery cannot enqueue a second nudge.
        db._exec('UPDATE task_reviews SET reviewer_nudged=1 WHERE conv_id=?', (conv_id,))
        await tell(runtime, att['id'], NUDGE)
    return task(db, conv_id)


async def env_gap(runtime, actor, conv_id, body):
    db = runtime.db
    async with task_lock(runtime, conv_id):
        row = require_task(db, actor, conv_id, reviewer=True)
        if row['status'] != 'in_review':
            raise HTTPException(409, 'no review is open')
        db._exec('UPDATE task_reviews SET reviewer_env_gap=1 WHERE conv_id=?', (conv_id,))
        await notify_root(runtime, row, f"Review environment gap in {body.repository}/{body.subpath}: "
                          f"{body.what_failed}; tried: {body.tried}")
    return task(db, conv_id)
