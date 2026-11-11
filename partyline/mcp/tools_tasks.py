"""Task tools available to the server-assigned root, implementer and reviewer."""

from urllib.parse import quote

from ..orchestrator_contracts import (
    BlockedIn, DeliverIn, MessageTaskIn, ReopenIn, ResumeIn, ReviewRequestIn, TaskIn, VerdictIn, WaitingIn)
from .client import ApiError
from .validation import validate_arguments

_MODELS = {'blocked': BlockedIn, 'deliver': DeliverIn, 'create_task': TaskIn,
           'request_review': ReviewRequestIn,
           'review_verdict': VerdictIn,
           'resume_work': ResumeIn, 'reopen_task': ReopenIn, 'message_task': MessageTaskIn,
           'waiting': WaitingIn, 'set_task_goal': ReopenIn}
_PATHS = {'blocked': ('POST', 'blocked'), 'deliver': ('POST', 'deliver'),
          'create_task': ('POST', 'tasks'), 'tasks': ('GET', 'tasks'),
          'request_review': ('POST', 'request-review'), 'review_verdict': ('POST', 'review-verdict'),
          'restart_reviewer': ('POST', 'task/reviewer'),
          'restart_implementer': ('POST', 'task/implementer'), 'resume_work': ('POST', 'task/resume'),
          'reopen_task': ('POST', 'task/reopen'), 'message_task': ('POST', 'task/message'),
          'waiting': ('POST', 'waiting'), 'set_task_goal': ('POST', 'task/goal')}
OPERATIONS = tuple(_PATHS)


_WHO = {'deliver': 'the implementer of an express task',
        'resume_work': "the task's implementer and the root captain",
        'blocked': "the task's implementer", 'request_review': "the task's implementer",
        'review_verdict': "the task's reviewer, or the root captain under captain review "
                          'or with an explicit override',
        'waiting': "the task's implementer"}


_DESCRIBE = {
    'create_task': ('START new work: creates a new task line (conv_id defaults to your root line) with one '
                    'implementer with Fast implementer checked; select a free one. Reviewers require '
                    'Can manage a line. Prefer Reads images for visual work. Its goal is stored on the task '
                    'line and sent to the implementer '
                    'at birth and on wakes until delivery is proven, then on change or restart. '
                    'Goals allow 20000 characters. '
                    'Media on your root line (a walkthrough\'s frames, uploads) is readable by the '
                    'task\'s workers with get_media: put the media ids in the goal, never stage files. '
                    'Optional memory_limit (e.g. "8G") starts a heavy line with a bigger budget, '
                    'within the host ceiling and, for a captain, the captain approval ceiling '
                    '(above it: 403, file a memory request for a person). '
                    'mode is full (default), light (review cycle, gates scaled to the diff) or express '
                    '(no reviewer, no review; the implementer ends with deliver; review omitted or '
                    'none); it cannot change later. '
                    'Retry with the same name and assignment to recover the existing task; '
                    'conflicting names are refused. '
                    'A creation_error means the task exists but staffing or notification needs attention.'),
    'deliver': ('END an express task: report results as text (what, where), no SHA. Posts the report '
                'to the root captain and marks the task done. Express tasks have no review.'),
    'request_review': 'Hand a full task to review (sha, what, where). Refused (409) on an express task.',
    'set_task_goal': ('CHANGE the direction of an EXISTING active task. conv_id is the task line id (from '
                      'create_task or tasks), never your root id. Does not start work or create anything; '
                      'refused for approved or done tasks (use reopen_task).'),
    'reopen_task': 'CONTINUE an approved or done EXISTING task with a new goal; conv_id is the task line id.',
    'message_task': 'Message an existing task participant privately; it does not change the goal.',
}


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
        if name in ('reopen_task', 'message_task', 'set_task_goal'):
            schema['properties']['conv_id'] = {'type': 'string', 'minLength': 1, 'description': (
                'Task line id, or the task tag, impl-/review- handle, or line name.')}
            schema['required'] = [*schema.get('required', []), 'conv_id']
        if name == 'resume_work' and state.get('is_lead'):
            schema['properties']['conv_id'] = {'type': 'string', 'minLength': 1}
            schema['required'] = [*schema.get('required', []), 'conv_id', 'note']
        if name == 'review_verdict' and state.get('is_lead'):
            schema['properties']['conv_id'] = {'type': 'string', 'minLength': 1}
            schema['required'].append('conv_id')
        description = _DESCRIBE.get(name, f'Server-authorized task operation: {name}.')
        if name == 'tasks':
            description += (" Workspaces show real and mirror tips; the mirror tip is where the worker's "
                            "commits live until accept.")
        result.append({'name': name, 'description': description, 'inputSchema': schema})
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
