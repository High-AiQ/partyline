"""Validate and apply the only captain-selectable preset command changes."""

import re
import shlex

from fastapi import HTTPException

_MODEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}\Z')
_EFFORT = {'claude': {'low', 'medium', 'high', 'xhigh', 'max'},
           'codex': {'minimal', 'low', 'medium', 'high', 'xhigh'}}


def rewrite(adapter, command, model=None, effort=None):
    if model is None and effort is None:
        return command
    if adapter not in _EFFORT:
        raise HTTPException(422, 'model and effort overrides support only claude and codex adapters')
    if model is not None and not _MODEL.fullmatch(model):
        raise HTTPException(422, 'invalid model override')
    if effort is not None and effort not in _EFFORT[adapter]:
        allowed = ', '.join(sorted(_EFFORT[adapter]))
        raise HTTPException(422, f'invalid effort for {adapter}: choose {allowed}')
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise HTTPException(422, 'invalid preset command') from exc
    if not argv:
        raise HTTPException(422, 'preset command must name an executable')
    if model is not None:
        _replace(argv, '--model', model, short='-m' if adapter == 'codex' else None)
    if effort is not None:
        if adapter == 'claude':
            _replace(argv, '--effort', effort)
        else:
            _config(argv, effort)
    return shlex.join(argv)


def _replace(argv, flag, value, short=None):
    found = False
    i = 1
    while i < len(argv) and argv[i] != "--":
        if argv[i] == flag or (short and argv[i] == short):
            if i + 1 >= len(argv) or argv[i + 1].startswith("-"):
                raise HTTPException(422, f'preset {flag} has no value')
            argv[i + 1] = value
            found = True
            i += 2
        elif argv[i].startswith(flag + '=') or (short and argv[i].startswith(short + '=')):
            option = argv[i].split('=', 1)[0]
            argv[i] = option + '=' + value
            found = True
            i += 1
        else:
            i += 1
    if not found:
        argv[i:i] = [flag, value]


def _config(argv, effort):
    found = False
    i = 1
    while i < len(argv) and argv[i] != "--":
        token = argv[i]
        if token in ('--config', '-c'):
            if i + 1 >= len(argv) or argv[i + 1].startswith('-'):
                raise HTTPException(422, 'preset config has no value')
            if re.match(r'^\s*model_reasoning_effort\s*=', argv[i + 1]):
                argv[i + 1] = f'model_reasoning_effort="{effort}"'
                found = True
            i += 2
        elif token.startswith('--config=') and re.match(
                r'^\s*model_reasoning_effort\s*=', token[len('--config='):]):
            argv[i] = f'--config=model_reasoning_effort="{effort}"'
            found = True
            i += 1
        else:
            i += 1
    if not found:
        argv[i:i] = ['--config', f'model_reasoning_effort="{effort}"']


def label(preset, model=None, effort=None):
    parts = [f'{key} {value}' for key, value in (('model', model), ('effort', effort)) if value is not None]
    return preset + (' (' + ', '.join(parts) + ')' if parts else '')


def attachment_command(db, body):
    if body.model is None and body.effort is None:
        return body.command, None
    if not body.preset_name:
        raise HTTPException(422, 'model and effort overrides require a preset')
    from .preset_roles import named_preset
    selected = named_preset(db, body.preset_name)
    if selected['adapter'] != body.adapter:
        raise HTTPException(422, 'preset adapter does not match')
    try:
        if body.command and shlex.split(body.command) != shlex.split(selected['command']):
            raise HTTPException(422, 'command must match the base preset')
    except ValueError as exc:
        raise HTTPException(422, 'invalid preset command') from exc
    return rewrite(body.adapter, selected['command'], body.model, body.effort), selected


def record_override(db, conv_id, actor, preset, model, effort, role):
    """Record the choice in the line's durable, attributed system message trail."""
    if model is None and effort is None:
        return
    from .hierarchy import stamp_source
    identity = actor.attachment_id if actor.kind == 'machine' else f'user:{actor.user_id}'
    body = (f'Preset override by {actor.name} ({identity}): role {role}, preset {preset}, '
            f'model {model if model is not None else "unchanged"}, '
            f'effort {effort if effort is not None else "unchanged"}')
    message = db.add_message(conv_id, 'system', 'system', body)
    stamp_source(db, message['id'], actor)


def save_attachment_override(db, att, selected, body, actor, role):
    db._exec('UPDATE attachments SET preset=?,model_override=?,effort_override=? WHERE id=?',
             (selected['name'], body.model, body.effort, att['id']))
    att.update(preset=selected['name'], model_override=body.model, effort_override=body.effort)
    record_override(db, att['conv_id'], actor, selected['name'], body.model, body.effort, role)


def record_task_overrides(db, conv_id, actor, body, policy):
    record_override(db, conv_id, actor, body.implementer, body.model, body.effort, 'implementer')
    record_override(db, conv_id, actor, policy, body.review_model, body.review_effort, 'reviewer')
