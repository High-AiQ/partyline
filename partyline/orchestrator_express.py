"""Reviewer-free express and suite tasks finish with a structured delivery."""

import asyncio
import time

from fastapi import HTTPException

from .contracts import ConversationsChangedEvent
from .orchestrator_notices import report
from .orchestrator_revive import task_lock
from .orchestrator_stall import resume
from .orchestrator_store import require_task, task

async def deliver(runtime, actor, conv_id, body):
    """Report results and mark done; suite delivery also records the integration branch tip."""
    db = runtime.db
    if require_task(db, actor, conv_id)['mode'] not in ('express', 'suite'):
        raise HTTPException(409, 'deliver is for express or suite tasks; a full task hands off with '
                            'request_review(sha, what, where)')
    async with task_lock(runtime, conv_id):
        row = require_task(db, actor, conv_id)
        if row['status'] in ('approved', 'done'):
            await report(runtime, row)  # a repeated call re-sends nothing new
            return task(db, conv_id, visibility=True)
        if row['mode'] == 'suite':
            from .orchestrator_suite import record_integration
            await asyncio.to_thread(record_integration, db, row)
        await asyncio.to_thread(resume, db, conv_id)
        db._exec("UPDATE task_reviews SET what=?,location=?,findings='',status='done',settled_at=?,"
                 'reopen_noticed=0,round=CASE WHEN round=0 THEN 1 ELSE round END WHERE conv_id=?',
                 (body.what, body.where, time.time(), conv_id))
        await report(runtime, task(db, conv_id))
        await runtime.broadcast_all(ConversationsChangedEvent())
        return task(db, conv_id, visibility=True)
