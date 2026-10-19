"""Task participants are briefed without the manager-tree worker wait rule."""

from .orchestrator_store import task


def task_pack(db, conv_id, role):
    if db is None or not hasattr(db, '_exec'):
        return ''
    row = task(db, conv_id)
    if not row:
        return ''
    return (
        '\n\n## Task line pack\n'
        f"You are the {role}. Task of {row['root_id']}, one implementer, policy {row['policy']}. "
        'The implementer follows the assigned goal and calls request_review(sha, what, where). '
        'If blocked, call blocked(reason); the server notifies the root. '
        'Without a structured call or peer, one reminder precedes a stalled report. '
        'The server selects and reuses the reviewer; workers cannot attach one. '
        'A reviewer works only in the managed review checkout at the exact requested SHA, '
        'does not implement or push, and calls review_verdict(approve|changes, findings). '
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
