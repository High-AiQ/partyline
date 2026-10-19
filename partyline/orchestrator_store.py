"""Task identities, policies and access decisions; never infer state from prose."""

from fastapi import HTTPException


def task(db, conv_id):
    if not hasattr(db, '_exec'):
        return None
    row = db._exec("SELECT * FROM task_reviews WHERE conv_id=?", (conv_id,)).fetchone()
    return dict(row) if row else None


def tasks(db, root_id):
    return [dict(row) for row in db._exec(
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
        actions.update(('request_review', 'blocked'))
    if actor.attachment_id == row['reviewer_id']:
        actions.add('review_verdict')
    if row['policy'] == 'captain' and actor.is_lead and actor.conv_id == row['root_id']:
        actions.add('review_verdict')
    return actions


def refuse_task_attach(db, conv_id):
    if task(db, conv_id):
        raise HTTPException(409, 'task staffing is server-owned: exactly one implementer')


def retained_task(db, conv_id, include_children=False):
    from .hierarchy import descendants
    ids = [conv_id, *descendants(db, conv_id)] if include_children else [conv_id]
    return any(task(db, line_id) for line_id in ids)


def attachment_task(db, ident):
    row = db._exec('SELECT * FROM task_reviews WHERE implementer_id=? OR reviewer_id=?',
                   (ident, ident)).fetchone()
    return dict(row) if row else None
