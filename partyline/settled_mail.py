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
# Restart and revival notes are filed when a worker comes back, so they can postdate settling:
# while the task is settled they mean nothing, whenever they were written (turn_marker, revive,
# and the reattach banner, which is public and carries the generic "continue the work" debrief).
CONTINUATION = re.compile(
    r"^(?:@\S+\s+)?(?:resumed by \S+; continue the task|"
    r"↻ @\S+ — your process was restarted in the middle of a turn)"
    r"|^☏ (?:@\S+ accepted|the restart plan started automatic) sequential reattachment "
    r"after the dogfood restart\n\nContinuation debrief:")


def _workers(row: dict) -> set:
    return {row['implementer_id'], row['reviewer_id']} - {None}


def is_stale(row: dict, att_id: str, message: dict) -> bool:
    """Whether ``message`` is system mail for a worker that its task's settling made void.

    Every private system notice to a worker filed before the task settled is task-work talk
    (the assignment, review requests, changes requested, stall reminders, admission refusals
    and their retry instructions): once the work is approved it is void, and a reopen starts
    from the reopen. ``consumed_through`` remembers that past a reopen. Restart and revival
    notes (``CONTINUATION``) can postdate the settling and are void while it lasts.
    """
    if message.get('sender_type') != 'system' or att_id not in _workers(row):
        return False
    audience = message.get('audience_attachment_id')
    body = str(message.get('body') or '')
    again = CONTINUATION.match(body)
    if audience != att_id and not (again and not audience):
        return False
    if message['id'] <= (row.get('consumed_through') or 0):
        return True
    if row['status'] not in SETTLED:
        return False
    if again:
        return True
    settled_at = row.get('settled_at')
    return settled_at is None or (message.get('created_at') or 0) <= settled_at


def drop_settled(db, att: dict, messages: list[dict], *, keep=frozenset()) -> list[dict]:
    """``messages`` without the notices a settled task's workers should no longer receive."""
    if not messages:
        return messages
    messages = drop_acknowledged_reports(db, messages, keep=keep)
    row = task(db, att['conv_id'])
    if row is None or (row['status'] not in SETTLED and not row.get('consumed_through')):
        return messages
    return [m for m in messages if m['id'] in keep or not is_stale(row, att['id'], m)]


def settled_worker(db, att: dict) -> bool:
    """Whether ``att`` is a worker of a task that is approved or done."""
    row = task(db, att['conv_id'])
    return bool(row and row['status'] in SETTLED and att['id'] in _workers(row))
