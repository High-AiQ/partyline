"""Task notices that stop being deliverable once their task is approved, accepted or done.

A review request, a stall reminder or a "continue the task" restart note is
only worth reading while the work it asks for is open. The cursor behind such
a notice does not always move (an unproved paste, a held wake, a resumed
session replaying its backlog), so every later wake of the worker pasted the
same round-1 request again — three times in a batch, until a captain detached
the worker. The state is checked at delivery time, never at queue time.
"""

from __future__ import annotations

import re

from .orchestrator_store import task

SETTLED = ('approved', 'done')
# What the task server says to a worker about work in flight (see orchestrator_revive,
# orchestrator_stall, orchestrator_service, orchestrator_goal and orchestrator_staff).
WORK_NOTICE = re.compile(
    r"^(?:@\S+\s+)?(?:Review round \d+|This (?:express )?task has no hand-off|"
    r"Changes requested; round|Task goal updated|Captain @\S+ overrode the review|"
    r"resumed by \S+; continue the task)")


def _workers(row: dict) -> set:
    return {row['implementer_id'], row['reviewer_id']} - {None}


def settled_row(db, conv_id: str) -> dict | None:
    """The task row when its work is finished (approved, accepted or done), else None."""
    row = task(db, conv_id)
    return row if row and row['status'] in SETTLED else None


def is_stale(row: dict, att_id: str, message: dict) -> bool:
    """Whether ``message`` is an in-flight-work notice to a worker that was sent before settling."""
    if message.get('sender_type') != 'system' or message.get('audience_attachment_id') != att_id:
        return False
    if att_id not in _workers(row):
        return False
    settled_at = row.get('settled_at')
    if settled_at is not None and (message.get('created_at') or 0) > settled_at:
        return False
    return bool(WORK_NOTICE.match(str(message.get('body') or '')))


def drop_settled(db, att: dict, messages: list[dict], *, keep=frozenset()) -> list[dict]:
    """``messages`` without the notices a settled task's workers should no longer receive."""
    if not messages:
        return messages
    row = settled_row(db, att['conv_id'])
    if row is None:
        return messages
    return [m for m in messages if m['id'] in keep or not is_stale(row, att['id'], m)]
