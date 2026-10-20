"""Task tools available to the server-assigned root, implementer and reviewer."""

from urllib.parse import quote

from ..orchestrator_contracts import BlockedIn, ReopenIn, ResumeIn, ReviewRequestIn, TaskIn, VerdictIn
from .client import ApiError
from .validation import validate_arguments

_MODELS = {'blocked': BlockedIn, 'create_task': TaskIn, 'request_review': ReviewRequestIn,
           'review_verdict': VerdictIn,
           'resume_work': ResumeIn, 'reopen_task': ReopenIn}
_PATHS = {'blocked': ('POST', 'blocked'), 'create_task': ('POST', 'tasks'), 'tasks': ('GET', 'tasks'),
          'request_review': ('POST', 'request-review'), 'review_verdict': ('POST', 'review-verdict'),
          'restart_reviewer': ('POST', 'task/reviewer'), 'resume_work': ('POST', 'task/resume'),
          'reopen_task': ('POST', 'task/reopen')}


def tool_list(state):
    result = []
    for name in _PATHS:
        if name not in state.get('actions', []):
            continue
        schema = _MODELS[name].model_json_schema() if name in _MODELS else {
            'type': 'object', 'properties': {}, 'additionalProperties': False}
        if name == 'restart_reviewer':
            schema = {'type': 'object', 'properties': {'conv_id': {'type': 'string', 'minLength': 1}},
                      'required': ['conv_id'], 'additionalProperties': False}
        if name == 'reopen_task':
            schema['properties']['conv_id'] = {'type': 'string', 'minLength': 1}
            schema['required'] = [*schema.get('required', []), 'conv_id']
        if name == 'review_verdict' and state.get('is_lead'):
            schema['properties']['conv_id'] = {'type': 'string', 'minLength': 1}
            schema['required'].append('conv_id')
        result.append({'name': name, 'description': f'Server-authorized task operation: {name}.',
                       'inputSchema': schema})
    return result


def call(client, name, args, state):
    available = {item['name']: item for item in tool_list(state)}
    if name not in available:
        raise ApiError('task operation is not currently available')
    validate_arguments(available[name]['inputSchema'], args)
    body = dict(args)
    conv = body.pop('conv_id', client.home)
    method, tail = _PATHS[name]
    return client.request(method, f"/api/conversations/{quote(conv, safe='')}/{tail}",
                          body if method == 'POST' else None)
