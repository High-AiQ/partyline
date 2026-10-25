"""Task tools available to the server-assigned root, implementer and reviewer."""

from urllib.parse import quote

from ..orchestrator_contracts import (
    BlockedIn, MessageTaskIn, ReopenIn, ResumeIn, ReviewRequestIn, TaskIn, VerdictIn)
from .client import ApiError
from .validation import validate_arguments

_MODELS = {'blocked': BlockedIn, 'create_task': TaskIn, 'request_review': ReviewRequestIn,
           'review_verdict': VerdictIn,
           'resume_work': ResumeIn, 'reopen_task': ReopenIn, 'message_task': MessageTaskIn}
_PATHS = {'blocked': ('POST', 'blocked'), 'create_task': ('POST', 'tasks'), 'tasks': ('GET', 'tasks'),
          'request_review': ('POST', 'request-review'), 'review_verdict': ('POST', 'review-verdict'),
          'restart_reviewer': ('POST', 'task/reviewer'),
          'restart_implementer': ('POST', 'task/implementer'), 'resume_work': ('POST', 'task/resume'),
          'reopen_task': ('POST', 'task/reopen'), 'message_task': ('POST', 'task/message')}
OPERATIONS = tuple(_PATHS)


_WHO = {'resume_work': "the task's implementer and the root captain",
        'blocked': "the task's implementer", 'request_review': "the task's implementer",
        'review_verdict': "the task's reviewer (or the root captain under captain review)"}


def _refusal(name):
    if name in _WHO:
        return f'{name} is available to {_WHO[name]}'
    if name in _PATHS:
        return f'{name} is available to the root captain'
    return 'task operation is not currently available'


def tool_list(state):
    result = []
    for name in _PATHS:
        if name not in state.get('actions', []):
            continue
        schema = _MODELS[name].model_json_schema() if name in _MODELS else {
            'type': 'object', 'properties': {}, 'additionalProperties': False}
        if name in ('restart_reviewer', 'restart_implementer'):
            schema = {'type': 'object', 'properties': {'conv_id': {'type': 'string', 'minLength': 1}},
                      'required': ['conv_id'], 'additionalProperties': False}
        if name in ('reopen_task', 'message_task'):
            schema['properties']['conv_id'] = {'type': 'string', 'minLength': 1, 'description': (
                'Task line id, or the task tag, impl-/review- handle, or line name.')}
            schema['required'] = [*schema.get('required', []), 'conv_id']
        if name == 'resume_work' and state.get('is_lead'):
            schema['properties']['conv_id'] = {'type': 'string', 'minLength': 1}
            schema['required'] = [*schema.get('required', []), 'conv_id', 'note']
        if name == 'review_verdict' and state.get('is_lead'):
            schema['properties']['conv_id'] = {'type': 'string', 'minLength': 1}
            schema['required'].append('conv_id')
        result.append({'name': name, 'description': f'Server-authorized task operation: {name}.',
                       'inputSchema': schema})
    return result


def call(client, name, args, state):
    available = {item['name']: item for item in tool_list(state)}
    if name not in available:
        raise ApiError(_refusal(name))
    validate_arguments(available[name]['inputSchema'], args)
    body = dict(args)
    conv = body.pop('conv_id', client.home)
    method, tail = _PATHS[name]
    return client.request(method, f"/api/conversations/{quote(conv, safe='')}/{tail}",
                          body if method == 'POST' else None)
