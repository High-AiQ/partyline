"""Task-derived process handles, and the root's id-addressed message to a task's workers."""

import hashlib
import re

from fastapi import HTTPException

from .auth_store import handle_taken
from .hierarchy import tree_live_name_conflict
from .mention_relay import LIVE, post_private
from .orchestrator_store import all_tasks, require_root, task, tasks

MAX_TAG = 25  # `review-` plus the tag must fit a 32-character handle


def pick_tag(db, conv_id):
    """The shortest prefix of the line id, at least six hex characters, no handle or tag uses."""
    digits = conv_id.replace('-', '').lower()
    if not re.fullmatch(r'[0-9a-f]+', digits):
        digits = hashlib.sha1(conv_id.encode()).hexdigest()
    for size in range(6, min(len(digits), MAX_TAG) + 1):
        tag = digits[:size]
        names = (f'impl-{tag}', f'review-{tag}')
        if (not db._exec('SELECT 1 FROM task_reviews WHERE tag=?', (tag,)).fetchone()
                and not any(tree_live_name_conflict(db, conv_id, name) or handle_taken(db, name)
                            for name in names)):
            return tag
    raise HTTPException(409, 'no free task handle; retry')


def task_line(db, actor, ref):
    """The task line a path names: its id, or a task's tag, handle or line name.

    A root captain's name is looked up among its own tasks; anyone else among every task.
    An unknown name comes back unchanged, so the caller's 404 stays exact.
    """
    if not isinstance(ref, str) or task(db, ref) is not None:
        return ref
    rows = tasks(db, actor.conv_id) if actor.kind == 'machine' else all_tasks(db)
    matches = [row['conv_id'] for row in rows if ref in (
        row['tag'], row['implementer_handle'], row['reviewer_handle'],
        (db.get_conversation(row['conv_id']) or {}).get('name'))]
    if len(matches) > 1:
        raise HTTPException(409, f'task name {ref} matches {len(matches)} tasks; use a line id')
    return matches[0] if matches else ref


async def message_task(runtime, actor, conv_id, body):
    """Deliver a private message to a task's current implementer or reviewer and wake it."""
    db = runtime.db
    row = task(db, conv_id)
    if row is None:
        raise HTTPException(404, 'task not found')
    require_root(db, actor, row['root_id'])
    ident = row['reviewer_id'] if body.to == 'reviewer' else row['implementer_id']
    att = db.get_attachment(ident) if ident else None
    if att is None or att['status'] not in LIVE:
        raise HTTPException(
            409, f'this task has no live {body.to} to message; call restart_{body.to}')
    source = actor.attachment_id and (actor.attachment_id, actor.conv_id) or None
    # Spoken in the captain's own name, so the task line and its process read
    # "[astra via «root»]: @impl … text", not a system notice quoting it.
    sender_type = 'human' if actor.kind != 'machine' else 'agent'
    await post_private(runtime, att['conv_id'], actor.name, sender_type,
                       f"@{att['name']} {body.text}", audience=ident, source=source)
    return task(db, conv_id)
