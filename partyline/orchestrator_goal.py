"""Update a task's persistent direction and notify its live participants."""

from fastapi import HTTPException

from .contracts import ConversationEvent
from .goal import set_goal
from .mention_relay import LIVE
from .orchestrator_notices import tell
from .orchestrator_store import require_root, task


async def set_task_goal(runtime, actor, conv_id, goal):
    db = runtime.db
    row = task(db, conv_id)
    if row is None:
        raise HTTPException(404, 'task not found')
    require_root(db, actor, row['root_id'])
    if row['status'] in ('approved', 'done'):
        raise HTTPException(409, 'use reopen_task(conv_id, goal) for an approved or done task')
    goal = goal.strip()
    conv = set_goal(db, conv_id, goal)
    for ident in (row['implementer_id'], row['reviewer_id']):
        att = db.get_attachment(ident) if ident else None
        if att and att['status'] in LIVE:
            await tell(runtime, ident, f'Task goal updated by the root captain: {goal}')
    await runtime.broadcast(conv_id, ConversationEvent(conversation=conv))
    return task(db, conv_id)
