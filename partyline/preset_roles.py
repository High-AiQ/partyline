"""One policy for assigning preset-backed processes to staffed roles."""

import shlex

from fastapi import HTTPException

from .preset_traits import coerce_traits, match_preset


ROLE_TRAITS = {
    'implementer': ('implements', 'Fast implementer'),
    'reviewer': ('can_manage', 'Can manage a line'),
    'captain': ('can_manage', 'Can manage a line'),
}


def require_role(preset, role, *, name=None):
    field, label = ROLE_TRAITS[role]
    if preset is None:
        raise HTTPException(403, f"preset '{name or 'unknown'}' cannot be staffed as {role}: "
                            f'a uniquely matching preset with {label} checked is required; '
                            'a person can change checkboxes in Settings → Presets')
    if not coerce_traits(preset)[field]:
        raise HTTPException(403, f"preset '{preset['name']}' cannot be staffed as {role}: "
                            f'{label} is not checked; a person can change its checkboxes '
                            'in Settings → Presets')
    return preset


def named_preset(db, name):
    matches = [p for p in db.list_presets() if p['name'] == name]
    if len(matches) != 1:
        raise HTTPException(400, f"preset '{name}' must identify exactly one preset")
    return matches[0]


def require_named_role(db, name, role):
    matches = [p for p in db.list_presets() if p['name'] == name]
    try:
        return require_role(matches[0] if len(matches) == 1 else None, role, name=name)
    except HTTPException as exc:
        if len(matches) != 1:
            raise HTTPException(400, exc.detail) from exc
        raise


def attachment_preset(db, att, presets=None):
    presets = db.list_presets() if presets is None else presets
    if recorded := att.get('preset'):
        matches = [preset for preset in presets if preset['name'].lower() == recorded.lower()]
        return matches[0] if len(matches) == 1 else None
    matched = match_preset(att, presets)
    if matched:
        return matched
    # Task handles and user-selected handles can differ from the preset name.
    # A command must identify exactly one preset; ambiguous commands fail closed.
    matches = []
    for preset in presets:
        try:
            command = shlex.split(preset['command'])
        except ValueError:
            continue
        if preset['adapter'] == att['adapter'] and command == list(att['command']):
            matches.append(preset)
    return matches[0] if len(matches) == 1 else None


def require_captain_assignment(db, conv_id, ident, before, *, person=False):
    if not person and ident and (not before or before['id'] != ident):
        target = db.get_attachment(ident)
        if target and target['conv_id'] == conv_id:
            require_role(attachment_preset(db, target), 'captain',
                         name=target.get('preset') or target['name'])


def is_helper(att):
    """Raw processes (idle-check, rotate-captain) hold no staffed role, counted or not.

    Counting toward the worker total is memory accounting: the captain that may delete a raw
    process and re-point its command may resume it too, trait or no trait."""
    return att['adapter'] == 'raw'


def require_resume(db, ident, *, person=False):
    from .orchestrator_store import attachment_task
    if person:
        return None
    att = db.get_attachment(ident)
    if not att:
        return
    task = attachment_task(db, ident)
    if task:
        reviewer = task['reviewer_id'] == ident
        role = 'reviewer' if reviewer else 'implementer'
        name = task['policy'] if reviewer else task['implementer_preset']
        require_named_role(db, name, role)
        return role
    else:
        if att.get('is_lead') or att.get('is_successor'):
            role = 'captain'
        elif is_helper(att):
            return None
        else:
            # No row records whether an agent or a person attached it, so a
            # non-task, non-helper process fails closed: an agent resuming it
            # needs the same Fast implementer preset it would to attach one.
            role = 'implementer'
        require_role(attachment_preset(db, att), role, name=att.get('preset') or att['name'])
        return role


def seat_captain(db, att):
    require_role(attachment_preset(db, att), 'captain', name=att.get('preset') or att['name'])
    with db.lock:
        changed = db.conn.execute(
            'UPDATE attachments SET is_lead=1 WHERE id=? AND NOT EXISTS '
            '(SELECT 1 FROM attachments WHERE conv_id=? AND is_lead=1)',
            (att['id'], att['conv_id']))
        db.conn.commit()
    if changed.rowcount != 1:
        raise HTTPException(409, 'this line already has a captain')


async def start_staffed(runtime, att, start, role, principal, auto_lead):
    if auto_lead:
        try:
            seat_captain(runtime.db, att)
        except BaseException:
            from .attachment_lifecycle import remove_stopped_record
            await runtime.db.set_attachment_status_async(att['id'], 'exited', att['runtime_owner'])
            await remove_stopped_record(runtime.db, att['id'], missing_ok=True)
            raise
        att['is_lead'] = True
    try:
        result = await start(att, staffing_role=role, principal=principal)
    except BaseException:
        if auto_lead:
            runtime.db._exec('UPDATE attachments SET is_lead=0 WHERE id=?', (att['id'],))
        raise
    if auto_lead:
        from .attachment_broadcast import broadcast_captain
        await broadcast_captain(runtime, att['conv_id'])
    return result
