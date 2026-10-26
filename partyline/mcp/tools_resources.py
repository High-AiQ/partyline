"""Task-owned resource tools with fixed, nonblocking routes."""

from urllib.parse import quote

from .client import ApiError
from .validation import validate_arguments


def tool_list(state):
    if state.get('role') not in ('implementer', 'reviewer'):
        return []
    name = {'type': 'string', 'minLength': 1, 'maxLength': 64,
            'pattern': r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$'}
    return [
        {'name': op, 'description': description, 'inputSchema': {
            'type': 'object', 'properties': {'name': name, **extra},
            'required': ['name'], 'additionalProperties': False}}
        for op, description, extra in (
            ('acquire_resource', 'Acquire before starting a job needing a declared resource. '
             'Advisory exclusive lease: returns held or queued immediately. When queued, wait for '
             'the private grant notice before starting; release when done.',
             {'note': {'type': 'string', 'maxLength': 500}}),
            ('release_resource', 'Release your own lease or cancel your queued request when done.', {}))]


def call(client, name, args, state):
    available = {t['name']: t for t in tool_list(state)}
    if name not in available:
        raise ApiError('resource leases are available to task implementers and reviewers')
    validate_arguments(available[name]['inputSchema'], args)
    tail = 'acquire' if name == 'acquire_resource' else 'release'
    return client.request('POST', f"/api/task/resources/{quote(args['name'], safe='')}/{tail}",
                          {'note': args.get('note', '')} if tail == 'acquire' else None)
