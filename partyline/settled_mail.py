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
from .resolved_notices import drop_acknowledged_reports

SETTLED = ('approved', 'done')
# What the task server says to a worker about work in flight (see orchestrator_revive,
# orchestrator_stall, orchestrator_service, orchestrator_goal and orchestrator_staff).
WORK_NOTICE = re.compile(
    r"^(?:@\S+\s+)?(?:Implement this task:|Review round \d+|This (?:express )?task has no hand-off|"
    r"Changes requested; round|Task goal updated|Captain @\S+ overrode the review)")
# Restart and revival notes are filed when a worker comes back, so they can postdate settling:
# while the task is settled they mean nothing, whenever they were written (turn_marker, revive).
CONTINUATION = re.compile(
    r"^(?:@\S+\s+)?(?:resumed by \S+; continue the task|"
    r"↻ @\S+ — your process was restarted in the middle of a turn)")


def _workers(row: dict) -> set:
    return {row['implementer_id'], row['reviewer_id']} - {None}


def is_stale(row: dict, att_id: str, message: dict) -> bool:
    """Whether ``message`` is an in-flight-work notice to a worker that was sent before settling.

    Settling is remembered past a reopen: ``consumed_through`` is the highest message id the
    settled task's notices covered, so a reopened task starts from the reopen, not the backlog.
    """
    if message.get('sender_type') != 'system' or message.get('audience_attachment_id') != att_id:
        return False
    body = str(message.get('body') or '')
    work, again = WORK_NOTICE.match(body), CONTINUATION.match(body)
    if att_id not in _workers(row) or not (work or again):
        return False
    if message['id'] <= (row.get('consumed_through') or 0):
        return True
    if row['status'] not in SETTLED or again:
        return row['status'] in SETTLED
    settled_at = row.get('settled_at')
    return not (settled_at is not None and (message.get('created_at') or 0) > settled_at)


def drop_settled(db, att: dict, messages: list[dict], *, keep=frozenset()) -> list[dict]:
    """``messages`` without the notices a settled task's workers should no longer receive."""
    if not messages:
        return messages
    messages = drop_acknowledged_reports(db, messages, keep=keep)
    row = task(db, att['conv_id'])
    if row is None or (row['status'] not in SETTLED and not row.get('consumed_through')):
        return messages
    return [m for m in messages if m['id'] in keep or not is_stale(row, att['id'], m)]
