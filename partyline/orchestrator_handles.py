"""Task-derived process handles, and the root's id-addressed message to a task's workers."""

import hashlib
import re

from fastapi import HTTPException

from .auth_store import handle_taken
from .hierarchy import tree_live_name_conflict
from .machine_scope import capability_state
from .mention_relay import LIVE, post_private
from .reattach_queue import no_live_detail
from .orchestrator_store import all_tasks, require_root, task, tasks
from .orchestrator_revive import task_lock

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
    named = [(row['conv_id'], db.get_conversation(row['conv_id']) or {}) for row in rows if ref in (
        row['tag'], row['implementer_handle'], row['reviewer_handle'],
        (db.get_conversation(row['conv_id']) or {}).get('name'))]
    # A name reused after a retirement means the live task; history is reached by line id.
    live = [conv_id for conv_id, conv in named if not conv.get('archived_at')]
    matches = live or [conv_id for conv_id, _ in named]
    if len(matches) > 1:
        raise HTTPException(409, f'task name {ref} matches {len(matches)} tasks; use a line id')
    return matches[0] if matches else ref


def capabilities_for(db, actor, ref):
    """The caller's capability state on the line `ref` names: id, task tag, handle or line name.

    The state's `target_conv_id` is the resolved line id. A ref naming no line is a 404 that
    quotes it, so it is never mistaken for an authorization refusal (empty `actions`).
    """
    target = task_line(db, actor, ref) if ref else ref
    if target and db.get_conversation(target) is None:
        raise HTTPException(404, f"no line or task matches '{ref}'")
    return capability_state(db, actor, target)


async def message_task(runtime, actor, conv_id, body):
    async with task_lock(runtime, conv_id):
        return await _message_task(runtime, actor, conv_id, body)


async def _message_task(runtime, actor, conv_id, body):
    """Deliver a private message to a task's current implementer or reviewer and wake it."""
    db = runtime.db
    row = task(db, conv_id)
    if row is None:
        raise HTTPException(404, 'task not found')
    require_root(db, actor, row['root_id'])
    ident = row['reviewer_id'] if body.to == 'reviewer' else row['implementer_id']
    att = db.get_attachment(ident) if ident else None
    if att is None or att['status'] not in LIVE:
        raise HTTPException(409, no_live_detail(runtime, att, body.to, ' to message'))
    source = actor.attachment_id and (actor.attachment_id, actor.conv_id) or None
    if (body.to == 'implementer' and body.hold_review and row['status'] == 'in_review'
            and row['sha']):
        db._exec("UPDATE task_reviews SET review_hold_sha=? WHERE conv_id=? AND status='in_review' "
                 'AND sha=?', (row['sha'], conv_id, row['sha']))
        reviewer_id = row['reviewer_id']
        if not reviewer_id and row['policy'] == 'captain':
            from .hierarchy import lead_attachment
            captain = lead_attachment(db, row['root_id'])
            reviewer_id = captain['id'] if captain else None
        if reviewer_id:
            from .orchestrator_notices import tell
            await tell(runtime, reviewer_id,
                       f"Captain changes are pending after SHA {row['sha'][:7]}; "
                       'hold your verdict until the implementer re-delivers.')
    # Spoken in the captain's own name, so the task line and its process read
    # "[astra via «root»]: @impl … text", not a system notice quoting it.
    sender_type = 'human' if actor.kind != 'machine' else 'agent'
    await post_private(runtime, att['conv_id'], actor.name, sender_type,
                       f"@{att['name']} {body.text}", audience=ident, source=source)
    return task(db, conv_id)


async def review_hold(runtime, actor, conv_id, body):
    """Release a captain message hold on an open task review."""
    async with task_lock(runtime, conv_id):
        return await _release_review_hold(runtime, actor, conv_id, body)


async def _release_review_hold(runtime, actor, conv_id, body):
    db = runtime.db
    row = task(db, conv_id)
    if row is None:
        raise HTTPException(404, 'task not found')
    require_root(db, actor, row['root_id'])
    if row['status'] != 'in_review':
        raise HTTPException(409, 'review hold can only be changed while review is open')
    if body.hold:
        raise HTTPException(422, 'review holds are set by message_task; pass hold=false to release')
    db._exec('UPDATE task_reviews SET review_hold_sha=NULL WHERE conv_id=?', (conv_id,))
    if row.get('review_hold_sha') and row.get('reviewer_id'):
        from .orchestrator_notices import tell
        await tell(runtime, row['reviewer_id'],
                   f"Captain released the review hold after SHA {row['review_hold_sha'][:7]}; "
                   'you may submit your verdict.')
    return task(db, conv_id)
