"""Task tools available to the server-assigned root, implementer and reviewer."""

from urllib.parse import quote

from ..orchestrator_contracts import (
    BlockedIn, EnvGapIn, DeliverIn, MessageTaskIn, ReopenIn, ResumeIn, ReviewRequestIn,
    SuiteReopenIn, TaskIn, VerdictIn, WaitingIn)
from .client import ApiError
from .validation import validate_arguments

_MODELS = {'env_gap': EnvGapIn, 'blocked': BlockedIn, 'deliver': DeliverIn, 'create_task': TaskIn,
           'request_review': ReviewRequestIn,
           'review_verdict': VerdictIn,
           'resume_work': ResumeIn, 'reopen_task': SuiteReopenIn, 'message_task': MessageTaskIn,
           'waiting': WaitingIn, 'set_task_goal': ReopenIn}
_PATHS = {'env_gap': ('POST', 'env-gap'), 'blocked': ('POST', 'blocked'), 'deliver': ('POST', 'deliver'),
          'create_task': ('POST', 'tasks'), 'tasks': ('GET', 'tasks'),
          'request_review': ('POST', 'request-review'), 'review_verdict': ('POST', 'review-verdict'),
          'restart_reviewer': ('POST', 'task/reviewer'),
          'restart_implementer': ('POST', 'task/implementer'), 'resume_work': ('POST', 'task/resume'),
          'reopen_task': ('POST', 'task/reopen'), 'message_task': ('POST', 'task/message'),
          'nudge_reviewer': ('POST', 'task/nudge-reviewer'),
          'waiting': ('POST', 'waiting'), 'set_task_goal': ('POST', 'task/goal')}
OPERATIONS = tuple(_PATHS)


_WHO = {'env_gap': "the task's reviewer", 'deliver': 'the implementer of an express or suite task',
        'resume_work': "the task's implementer and the root captain",
        'blocked': "the task's implementer", 'request_review': "the task's implementer",
        'review_verdict': "the task's reviewer, or the root captain under captain review "
                          'or with an explicit override',
        'waiting': "the task's implementer or reviewer",
        'nudge_reviewer': "the task's implementer"}


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
                    'mode is full (default: review as needed, only affected tests), express '
                    '(no review or tests, when a person says so or the captain decides), or suite '
                    '(no reviewer: run every suite on the merged batch before every batch PR). '
                    'Suite requires repositories=[{repository, batch}, ...], or the legacy repository '
                    'and batch form; never mix forms or repeat repositories. Batches contain task line '
                    'IDs/tags resolving to accepted SHAs for that repository and/or explicit SHAs in '
                    'cherry-pick order. One runner creates an integration branch from current main in '
                    'each repository worktree, cherry-picks each batch, runs every repository\'s suites '
                    'and one combined end-to-end run across all trees. It ends with deliver naming '
                    'per-repo SHAs in repositories, each suite pass/fail, and best-effort '
                    'failure attribution. '
                    'It never pushes or opens a PR; the captain does both after a pass. Full tasks '
                    'never run full suites, e2e suites or whole-suite coverage; list scoped tests run. '
                    'Express and suite end with deliver; omit review or pass none. Mode is fixed. '
                    'Retry with the same name and assignment to recover the existing task; '
                    'conflicting names are refused. '
                    'A creation_error means the task exists but staffing or notification needs attention.'),
    'deliver': ('END an express or suite task: report results as text (what, where). Posts the report '
                'to the root captain and marks the task done. Suite reports name branch/SHA, pass/fail per '
                'suite and best-effort failure attribution; optionally pass '
                'repositories=[{repository, sha}, ...] '
                'to verify every integration tip. Neither mode has a reviewer.'),
    'request_review': ('Hand a full task to review (sha, what, where). '
                       'Refused (409) on an express or suite task.'),
    'set_task_goal': ('CHANGE the direction of an EXISTING active task. conv_id is the task line id (from '
                      'create_task or tasks), never your root id. Does not start work or create anything; '
                      'refused for approved or done tasks (use reopen_task).'),
    'reopen_task': 'CONTINUE an approved or done EXISTING task with a new goal; conv_id is the task line id. '
                   'For suite mode, omit batch inputs to keep all repositories; pass repositories '
                   '(per-repo ordered batches) to replace them, or batch with repository to update one.',
    'nudge_reviewer': 'Ask your reviewer to continue, once per round, with fixed text and no arguments.',
    'message_task': ('Message a task participant privately; while the task is in review, messages to '
                     'the implementer hold approval of the current SHA by default. Set hold_review=false '
                     'for an informational message. Release with captain(op="review_hold", '
                     'args={conv_id, hold: false}) or clear it by re-delivering.'),
}


BOARD_TEXT = 240
RETIRED_PAGE = 10
_PROSE = ('goal', 'what', 'location', 'findings', 'previous_findings', 'wait_reason')


# Bookkeeping a captain never acts on: ids the handles already name, and counters at rest.
_INTERNAL = ('root_id', 'implementer_id', 'reviewer_id', 'initial_status', 'status_pre_idle')
_COUNTERS = ('stall_stage', 'reviewer_restarts', 'reopen_noticed', 'repin_required')
RETIRED_TEXT = 80


def _board(rows, retired=False):
    """A listing a captain can read whole: unset fields dropped, long prose cut short.

    A full record runs to kilobytes and the reply is bounded, so a few tasks' findings
    used to push every later task off the end of the listing. A retired task keeps its
    outcome and a short goal; `tasks(conv_id=...)` still returns any task in full.
    """
    board = []
    for row in rows if isinstance(rows, list) else []:
        item = {key: value for key, value in row.items()
                if value not in (None, '', []) and key not in _INTERNAL
                and not (key in _COUNTERS and value == 0)}
        for key in _PROSE:
            limit = RETIRED_TEXT if retired else BOARD_TEXT
            if isinstance(item.get(key), str) and len(item[key]) > limit:
                item[key] = item[key][:limit] + '…'
        board.append(item)
    return board


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
            schema['properties']['include_retired'] = {'type': 'boolean', 'description': (
                'Also list tasks whose line is retired, oldest first. Default false: the live board.')}
            schema['properties']['conv_id'] = {'type': 'string', 'minLength': 1, 'description': (
                'A task line id: return that one task with no field shortened.')}
            schema['properties']['limit'] = {'type': 'integer', 'minimum': 1, 'maximum': 100, 'description': (
                f'With include_retired: retired tasks per page, newest first; default {RETIRED_PAGE}.')}
            schema['properties']['offset'] = {'type': 'integer', 'minimum': 0, 'description': (
                'With include_retired: skip this many retired tasks (the board says what to pass).')}
            description = ("The board: every task on a live line, with status, handles and workspaces. "
                           "Workspaces show real and mirror tips; the mirror tip is where the worker's "
                           f"commits live until accept. Text over {BOARD_TEXT} characters is cut short; "
                           "pass conv_id for one task in full.")
        result.append({'name': name, 'description': description, 'inputSchema': schema})
    return result


def call(client, name, args, state):
    if name == 'create_task' and args.get('mode') == 'light':
        args = dict(args, mode='full')  # retired callers work without advertising a fourth choice
    available = {item['name']: item for item in tool_list(state)}
    if name not in available:
        raise ApiError(_refusal(name))
    validate_arguments(available[name]['inputSchema'], args)
    body = dict(args)
    conv = body.pop('conv_id', client.home)
    method, tail = _PATHS[name]
    if name == 'tasks' and 'conv_id' in args:
        return client.request('GET', f"/api/conversations/{quote(conv, safe='')}/task")
    if name == 'tasks':
        base = f"/api/conversations/{quote(conv, safe='')}/tasks"
        board = _board(client.request('GET', base))
        if not body.get('include_retired'):
            return board
        limit, offset = body.get('limit', RETIRED_PAGE), body.get('offset', 0)
        old = _board(client.request('GET', f'{base}?retired_only=true&limit={limit + 1}&offset={offset}'),
                     retired=True)
        if len(old) > limit:
            old = [*old[:limit], {'retired_more': f'tasks(include_retired=true, offset={offset + limit})'}]
        return board + old
    return client.request(method, f"/api/conversations/{quote(conv, safe='')}/{tail}",
                          body if method == 'POST' else None)
