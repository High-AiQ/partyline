"""Task participants are briefed without the manager-tree worker wait rule."""

from .mention_relay import task_root_captain
from .orchestrator_store import task
from .task_workspaces import workspaces


def _root_sentence(db, conv_id, root_id):
    root = db.get_conversation(root_id) or {}
    captain = task_root_captain(db, conv_id)
    line = f"Root line «{root.get('name', root_id)}»"
    if captain is None:
        return f'{line} has no live captain right now. '
    return (f"{line}, root captain @{captain['name']}. To reach the root captain, "
            f"mention @{captain['name']}; line names are not mentionable. ")


def _handles(row, role):
    tag = row.get('tag')
    own = row['reviewer_handle'] if role == 'reviewer' else row['implementer_handle']
    other_role = 'implementer' if role == 'reviewer' else 'reviewer'
    other = row['implementer_handle'] if role == 'reviewer' else (
        row['reviewer_handle'] or (f'review-{tag}' if tag else None))
    text = f'Your handle is {own}. ' if own else ''
    if other:
        text += f'The {other_role} of this task is {other}. '
    return text


def _workspace_sentence(db, conv_id, role):
    spaces = workspaces(db, conv_id)
    if not spaces:
        return ''
    if role == 'reviewer':
        return 'The task changed one or more repositories; review each checkout you are given. '
    return (f"Your folder holds a git worktree of each repository ({len(spaces)}), every one on branch "
            f"{spaces[0]['branch']}. Commit in the repository folder you changed, never push. "
            'request_review() with no arguments reviews every repository whose branch moved. ')


def task_pack(db, conv_id, role):
    if db is None or not hasattr(db, '_exec'):
        return ''
    row = task(db, conv_id)
    if not row:
        return ''
    return (
        '\n\n## Task line pack\n'
        f"You are the {role}. Task of {row['root_id']}, one implementer, policy {row['policy']}. "
        f"{_handles(row, role)}"
        f"{_root_sentence(db, conv_id, row['root_id'])}"
        f"{_workspace_sentence(db, conv_id, role)}"
        'The implementer follows the assigned goal and calls request_review(sha, what, where). '
        'If blocked, call blocked(reason); the server notifies the root. '
        'If you were blocked and resume work, call resume_work(note) — your task state must '
        'always reflect what you are doing. '
        'Never send acknowledgment-only replies to the root captain or anyone else: reply only '
        'with results, questions or a status change, or react instead. '
        'Without a structured call or peer, one reminder precedes a stalled report. '
        'The server selects and reuses the reviewer; workers cannot attach one. '
        'A reviewer works only in the managed review checkout at the exact requested SHA, '
        'does not implement or push, and calls review_verdict(approve|changes, findings). '
        'New work on an approved or done task arrives only through the root captain\'s '
        'reopen_task, which returns it to implementing with a new goal. '
        'Approval is acceptance. Changes ring the implementer and increase the round count; '
        'there is no round cap. Use structured tools for state, never chat verdicts. '
        'While reviewing, hand off only between the implementer and reviewer. '
        'The root captain receives one terminal report and always merges and pushes. '
        'Never archive or retire this task line. Processes detach after work ships. '
        f"Current state: {row['status']}, round {row['round']}, SHA {row['sha']}, "
        f"review checkout {row['review_worktree']}. "
        f"Request: {row['what'][:300]} — {row['location'][:200]}. "
        f"Findings: {row['findings'][:400]}. "
        f"Full current task state: GET /api/conversations/{conv_id}/task."
    )


def task_rebrief(db, att):
    row = task(db, att['conv_id'])
    if row is None:
        return ''
    role = 'reviewer' if row['reviewer_id'] == att['id'] else 'implementer'
    return task_pack(db, att['conv_id'], role)
