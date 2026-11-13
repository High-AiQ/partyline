"""Task identities, policies and access decisions; never infer state from prose."""

import json

from fastapi import HTTPException

from .task_workspaces import workspaces
from .workspace_visibility import workspace_visibility


EXPRESS_NO_REVIEW = 'express task: no review — report results with deliver(what, where)'
EXPRESS_BRIEF = 'Express task: no review. Call deliver(what, where) with the results when done.'


def _handle(db, ident):
    att = db.get_attachment(ident) if ident and hasattr(db, 'get_attachment') else None
    return att['name'] if att else None


def _parsed(row, db=None, visibility=False):
    if row is None:
        return None
    record = dict(row)
    conv = db.get_conversation(record['conv_id']) if db else None
    record['goal'] = (conv or {}).get('goal', '')
    record['creation_error'] = None
    record['implementer_handle'] = _handle(db, record.get('implementer_id'))
    record['reviewer_handle'] = _handle(db, record.get('reviewer_id'))
    try:
        record['repositories'] = json.loads(record.get('repositories') or '[]')
    except ValueError:
        record['repositories'] = []
    if visibility:
        record['workspaces'] = workspace_visibility(db, record)
    return record


def task(db, conv_id, visibility=False):
    if not hasattr(db, '_exec'):
        return None
    return _parsed(db._exec("SELECT * FROM task_reviews WHERE conv_id=?", (conv_id,)).fetchone(),
                   db, visibility)


def tasks(db, root_id, visibility=False, retired=True, only_retired=None):
    """A root's tasks, oldest first; ``retired=False`` leaves out tasks whose line is retired.

    ``only_retired=(limit, offset)`` returns just the retired ones, newest first, that page of them.
    """
    live = "" if retired else ("AND EXISTS(SELECT 1 FROM conversations c "
                               "WHERE c.id=task_reviews.conv_id AND c.archived_at IS NULL) ")
    order, tail, params = "ORDER BY created_at,conv_id", "", [root_id]
    if only_retired is not None:
        live = ("AND EXISTS(SELECT 1 FROM conversations c "
                "WHERE c.id=task_reviews.conv_id AND c.archived_at IS NOT NULL) ")
        order, tail = "ORDER BY created_at DESC,conv_id", " LIMIT ? OFFSET ?"
        params = [root_id, *only_retired]
    rows = [_parsed(row, db, visibility=visibility) for row in db._exec(
        f"SELECT * FROM task_reviews WHERE root_id=? {live}{order}{tail}", params).fetchall()]
    for record in rows:
        # A new task's workspaces are its repositories (create_task says so);
        # a reviewed task keeps the SHAs it was reviewed with.
        if not record['repositories']:
            record['repositories'] = [
                {'repository': item['repository'], 'sha': item['base_sha'], 'path': item['path']}
                for item in workspaces(db, record['conv_id'])]
    return rows


def all_tasks(db):
    return [_parsed(row, db) for row in db._exec(
        "SELECT * FROM task_reviews ORDER BY created_at,conv_id").fetchall()]


def preset(db, name):
    from .preset_roles import named_preset
    return named_preset(db, name)


def validate_policy(db, policy):
    if policy not in ('none', 'captain'):
        from .preset_roles import require_named_role
        require_named_role(db, policy, 'reviewer')
    return policy


def write_captain_style(db, actor, conv_id, captain_mode, policy):
    """Person-only, root-only style write shared by captain-style and appointing."""
    if actor.kind != 'user':
        raise HTTPException(403, 'only a person changes captain style')
    conv = db.get_conversation(conv_id)
    if conv['parent_id'] is not None:
        raise HTTPException(409, 'captain style can only be set on a root line')
    validate_policy(db, policy)
    db._exec('UPDATE conversations SET captain_mode=?,default_review_policy=? WHERE id=?',
             (captain_mode, policy, conv_id))
    return db.get_conversation(conv_id)


def require_root(db, actor, root_id):
    from .machine_scope import deny_unless
    deny_unless(db, actor, root_id, 'assign')
    conv = db.get_conversation(root_id)
    if task(db, root_id):
        raise HTTPException(409, 'task lines cannot create tasks')
    if actor.kind == 'machine' and actor.conv_id != root_id:
        raise HTTPException(403, 'only the root captain creates and lists tasks')
    return conv


def require_task(db, actor, conv_id, *, reviewer=False):
    row = task(db, conv_id)
    if row is None:
        raise HTTPException(404, 'task not found')
    ident = row['reviewer_id'] if reviewer else row['implementer_id']
    if reviewer and row['policy'] == 'captain':
        from .hierarchy import lead_attachment
        captain = lead_attachment(db, row['root_id'])
        ident = captain['id'] if captain else None
    if actor.kind != 'machine' or actor.attachment_id != ident:
        raise HTTPException(403, 'only the assigned task process may perform this operation')
    return row


def require_override(db, actor, conv_id):
    """The task row and its root captain, for an explicit override verdict.

    The reviewer-of-record rule stays: an ordinary verdict call remains the
    reviewer's alone. An override is the captain's explicit, auditable act, so
    it needs the live lead of the task's root line and a review that belongs to
    a staffed reviewer preset. Returns ``(row, captain)`` so the caller records
    the same captain it authorized.
    """
    row = task(db, conv_id)
    if row is None:
        raise HTTPException(404, 'task not found')
    from .hierarchy import lead_attachment
    captain = lead_attachment(db, row['root_id'])
    if (actor.kind != 'machine' or captain is None or actor.conv_id != row['root_id']
            or actor.attachment_id != captain['id']):
        raise HTTPException(403, 'only the root captain of this task may override its review')
    if row['policy'] in ('none', 'captain'):
        raise HTTPException(
            409, 'override applies only to a review that belongs to a separate reviewer; '
            "for a captain-policy task record the verdict with review_verdict directly")
    return row, captain


def require_task_or_root(db, actor, conv_id):
    """The task row and whether the root captain (or a person) is the caller; else its implementer."""
    row = task(db, conv_id)
    if row is None:
        raise HTTPException(404, 'task not found')
    if actor.kind == 'machine' and actor.attachment_id == row['implementer_id']:
        return row, False
    if actor.kind == 'machine' and not (actor.is_lead and actor.conv_id == row['root_id']):
        raise HTTPException(403, "only the task's implementer or the root captain may perform this operation")
    require_root(db, actor, row['root_id'])
    return row, True


def task_actions(db, actor, conv_id):
    row = task(db, conv_id)
    if not row:
        return set()
    actions = set()
    if actor.attachment_id == row['implementer_id']:
        actions.update(('request_review', 'blocked', 'resume_work', 'waiting'))
        if row['mode'] == 'express':
            actions.add('deliver')
    if actor.attachment_id == row['reviewer_id']:
        actions.add('review_verdict')
    if row['policy'] == 'captain' and actor.is_lead and actor.conv_id == row['root_id']:
        actions.add('review_verdict')
    return actions


def refuse_task_attach(db, conv_id):
    if task(db, conv_id):
        raise HTTPException(409, 'task staffing is server-owned: exactly one implementer; '
                            'a detached implementer or reviewer is revived with '
                            'captain(op="restart_implementer" or "restart_reviewer")')


def task_not_retirable_by(db, principal, conv_id, include_children=False):
    """A task line in scope that `principal` is not the live root captain of."""
    from .hierarchy import descendants
    ids = [conv_id, *descendants(db, conv_id)] if include_children else [conv_id]
    rows = [row for row in (task(db, line_id) for line_id in ids) if row]
    return any(not (principal.is_lead and principal.conv_id == row['root_id']) for row in rows)


def attachment_task(db, ident):
    row = db._exec('SELECT * FROM task_reviews WHERE implementer_id=? OR reviewer_id=?',
                   (ident, ident)).fetchone()
    return _parsed(row, db)
