"""Task identities, policies and access decisions; never infer state from prose."""

import json

from fastapi import HTTPException


def _handle(db, ident):
    att = db.get_attachment(ident) if ident and hasattr(db, 'get_attachment') else None
    return att['name'] if att else None


def _parsed(row, db=None):
    if row is None:
        return None
    record = dict(row)
    record['implementer_handle'] = _handle(db, record.get('implementer_id'))
    record['reviewer_handle'] = _handle(db, record.get('reviewer_id'))
    try:
        record['repositories'] = json.loads(record.get('repositories') or '[]')
    except ValueError:
        record['repositories'] = []
    return record


def task(db, conv_id):
    if not hasattr(db, '_exec'):
        return None
    return _parsed(db._exec("SELECT * FROM task_reviews WHERE conv_id=?", (conv_id,)).fetchone(), db)


def tasks(db, root_id):
    return [_parsed(row, db) for row in db._exec(
        "SELECT * FROM task_reviews WHERE root_id=? ORDER BY created_at,conv_id",
        (root_id,)).fetchall()]


def preset(db, name):
    matches = [row for row in db.list_presets() if row['name'] == name]
    if len(matches) != 1:
        raise HTTPException(400, 'name must identify exactly one preset')
    return matches[0]


def validate_policy(db, policy):
    if policy not in ('none', 'captain'):
        preset(db, policy)
    return policy


def write_captain_style(db, actor, conv_id, captain_mode, policy):
    """Person-only, root-only style write shared by captain-style and appointing."""
    if actor.kind != 'user':
        raise HTTPException(403, 'only a person changes captain style')
    conv = db.get_conversation(conv_id)
    if conv['parent_id'] is not None:
        raise HTTPException(409, 'captain style can only be set on a root line')
    if conv['captain_mode'] != captain_mode and db._exec(
            'SELECT 1 FROM conversations WHERE parent_id=? AND archived_at IS NULL LIMIT 1',
            (conv_id,)).fetchone():
        raise HTTPException(409, 'captain style cannot change while active child lines exist')
    validate_policy(db, policy)
    db._exec('UPDATE conversations SET captain_mode=?,default_review_policy=? WHERE id=?',
             (captain_mode, policy, conv_id))
    return db.get_conversation(conv_id)


def require_root(db, actor, root_id):
    from .machine_scope import deny_unless
    deny_unless(db, actor, root_id, 'assign')
    conv = db.get_conversation(root_id)
    if conv['parent_id'] is not None or conv['captain_mode'] != 'orchestrator':
        raise HTTPException(409, 'this operation requires an orchestrator root')
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


def task_actions(db, actor, conv_id):
    row = task(db, conv_id)
    if not row:
        return set()
    actions = set()
    if actor.attachment_id == row['implementer_id']:
        actions.update(('request_review', 'blocked', 'resume_work'))
    if actor.attachment_id == row['reviewer_id']:
        actions.add('review_verdict')
    if row['policy'] == 'captain' and actor.is_lead and actor.conv_id == row['root_id']:
        actions.add('review_verdict')
    return actions


def refuse_task_attach(db, conv_id):
    if task(db, conv_id):
        raise HTTPException(409, 'task staffing is server-owned: exactly one implementer')


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
