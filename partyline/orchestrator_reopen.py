"""New work on a settled task line: an explicit reopen, never a silent chat hand-off."""

from fastapi import HTTPException

from .contracts import ConversationsChangedEvent
from .goal import set_goal
from .mention_relay import LIVE, live_manager
from .orchestrator_notices import tell
from .orchestrator_revive import task_lock
from .orchestrator_staff import restart
from .orchestrator_store import require_root, task


async def reopen_task(runtime, actor, conv_id, body):
    """Return an approved or done task to implementing with a new goal and review cycle.

    The earlier approval stays in the accept history, reports and merge record.
    """
    db = runtime.db
    row = task(db, conv_id)
    if row is None:
        raise HTTPException(404, 'task not found')
    require_root(db, actor, row['root_id'])
    goal = body.goal.strip()
    async with task_lock(runtime, conv_id):
        changed = db._exec(
            "UPDATE task_reviews SET status='implementing',round=0,sha=NULL,review_worktree=NULL,"
            "repositories='[]',what='',location='',findings='',previous_findings='',report_id=NULL,reviewer_restarts=0,"
            'stall_stage=0,stall_notice_id=NULL,blocked_at=NULL,settled_at=NULL,reopen_noticed=0 '
            "WHERE conv_id=? AND status IN ('approved','done')", (conv_id,))
        if changed.rowcount != 1:
            raise HTTPException(
                409, 'only an approved or done task can be reopened; a blocked or implementing task '
                'takes new direction through resume_work(conv_id, note) or message_task')
        set_goal(db, conv_id, goal)
        att = db.get_attachment(row['implementer_id'])
        if att and att['status'] not in LIVE:
            await restart(runtime, att)
    await tell(runtime, row['implementer_id'],
               f'New work on this task, reopened by the root captain: {goal}. Commit on this '
               "line's branch; never push. Call request_review(sha, what, where) when ready.")
    await runtime.broadcast_all(ConversationsChangedEvent())
    return task(db, conv_id)


async def unreopened(runtime, att):
    """An implementer working again on a settled task gets its root captain one notice."""
    from .orchestrator_stall import directed
    db = runtime.db
    row = task(db, att['conv_id'])
    if not (row and row['implementer_id'] == att['id'] and row['status'] in ('approved', 'done')
            and not row['reopen_noticed'] and directed(db, row, row['settled_at'])):
        return
    claim = db._exec('UPDATE task_reviews SET reopen_noticed=1 WHERE conv_id=? AND reopen_noticed=0',
                     (row['conv_id'],))
    if claim.rowcount != 1:
        return
    captain = live_manager(runtime, row['root_id'])
    if captain is None:
        db._exec('UPDATE task_reviews SET reopen_noticed=0 WHERE conv_id=?', (row['conv_id'],))
        return
    name = db.get_conversation(row['conv_id'])['name']
    await tell(runtime, captain['id'],
               f"task «{name}» is approved but @{att['name']} is working again — call "
               f"reopen_task({row['conv_id']}, goal) so its state is tracked, or create_task "
               'for unrelated work')
