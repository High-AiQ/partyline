"""Structured task lifecycle; task policy is chosen only by the root captain."""

import asyncio
import time
import uuid

from fastapi import HTTPException

from .child_create import create_child
from .contracts import ConversationsChangedEvent
from .hierarchy_contracts import ChildIn
from .line_worktree import line_cwd, rev
from .git_fence import mirror_branch_ref
from .worktree_paths import branch_name
from .review_worktrees import ReviewError, create_review_worktree
from .orchestrator_notices import handed_to, report, spawn_refused, tell
from .orchestrator_staff import ensure_reviewer, restart, spawn
from .orchestrator_store import preset, require_root, require_task, task, validate_policy


async def create_task(runtime, actor, root_id, body):
    db = runtime.db
    root = require_root(db, actor, root_id)
    preset(db, body.implementer)
    policy = validate_policy(db, body.review or root['default_review_policy'])
    pending = db._exec(
        'SELECT t.* FROM task_reviews t JOIN conversations c ON c.id=t.conv_id '
        'LEFT JOIN attachments a ON a.id=t.implementer_id '
        "WHERE t.root_id=? AND c.name=? AND c.goal=? AND t.implementer_preset=? AND t.policy=? "
        "AND t.status='implementing' AND c.archived_at IS NULL "
        "AND (a.id IS NULL OR (a.status='exited' AND a.cli_session IS NULL)) LIMIT 1",
        (root_id, body.name.strip(), body.goal.strip(), body.implementer, policy)).fetchone()
    if pending:
        conv_id, ident = pending['conv_id'], pending['implementer_id']
    else:
        result = await create_child(runtime, actor, root_id, ChildIn(name=body.name, goal=body.goal))
        conv_id, ident = result.conversation.id, str(uuid.uuid4())
        db._exec(
            'INSERT INTO task_reviews(conv_id,root_id,implementer_id,implementer_preset,policy,created_at) '
            'VALUES(?,?,?,?,?,?)', (conv_id, root_id, ident, body.implementer, policy, time.time()))
    try:
        existing = db.get_attachment(ident)
        if existing:
            await restart(runtime, existing)
        else:
            await spawn(runtime, conv_id, body.implementer, ident)
    except (HTTPException, ValueError) as exc:
        await spawn_refused(runtime, task(db, conv_id), getattr(exc, 'detail', str(exc)), implementer=True)
        raise
    await tell(runtime, ident,
               f"Implement this task: {body.goal}. Commit on this line's branch; never push. "
               'Call request_review(sha, what, where) when ready. The server owns review staffing.')
    await runtime.broadcast_all(ConversationsChangedEvent())
    return task(db, conv_id)


async def request_review(runtime, actor, conv_id, body):
    db = runtime.db
    row = require_task(db, actor, conv_id)
    # A task lock spans worktree creation, admission and notification: duplicate
    # calls cannot spawn two reviewers or produce two terminal reports.
    locks = getattr(runtime, 'task_review_locks', None)
    if locks is None:
        runtime.task_review_locks = locks = {}
    async with locks.setdefault(conv_id, asyncio.Lock()):
        row = require_task(db, actor, conv_id)
        if row['status'] in ('approved', 'done'):
            await report(runtime, row)
            return task(db, conv_id)
        if row['status'] == 'in_review':
            return task(db, conv_id)
        from .orchestrator_stall import resume
        resume(db, conv_id)
        cwd = line_cwd(db, conv_id)
        tip = mirror_branch_ref(cwd or '', conv_id, branch_name(cwd or ''))
        sha = body.sha or tip or rev(cwd or '', 'rev-parse', 'HEAD')
        if not sha:
            raise HTTPException(409, 'task has no commit to review')
        try:
            checkout = await asyncio.to_thread(create_review_worktree, db, conv_id, sha)
        except ReviewError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc
        db._exec(
            'UPDATE task_reviews SET sha=?,review_worktree=?,what=?,location=?, '
            'round=CASE WHEN round=0 THEN 1 ELSE round END WHERE conv_id=?',
            (checkout['sha'], checkout['path'], body.what, body.where, conv_id))
        row = task(db, conv_id)
        if row['policy'] not in ('none', 'captain'):
            try:
                reviewer = await ensure_reviewer(runtime, row)
            except (HTTPException, ValueError) as exc:
                await spawn_refused(runtime, row, getattr(exc, 'detail', str(exc)))
                raise
        db._exec('UPDATE task_reviews SET status=? WHERE conv_id=?',
                 ('done' if row['policy'] == 'none' else 'in_review', conv_id))
        row = task(db, conv_id)
        if row['policy'] not in ('none', 'captain'):
            await tell(runtime, reviewer['id'],
                       f"Review round {row['round']} at exact SHA {row['sha']} in "
                       f"{row['review_worktree']}. {row['what']} — {row['location']}. "
                       'Call review_verdict(approve|changes, findings). Never push or implement. '
                       'Your approval is acceptance; the root captain merges.',
                       source=(row['implementer_id'], conv_id))
            handed_to(runtime, row['implementer_id'], reviewer['id'])
        await report(runtime, row)
        await runtime.broadcast_all(ConversationsChangedEvent())
        return task(db, conv_id)


async def review_verdict(runtime, actor, conv_id, body):
    db = runtime.db
    row = require_task(db, actor, conv_id, reviewer=True)
    approved = body.verdict == 'approve'
    changed = db._exec(
        'UPDATE task_reviews SET status=?,findings=?,round=round+? '
        "WHERE conv_id=? AND status='in_review'",
        ('approved' if approved else 'implementing', body.findings, int(not approved), conv_id))
    if changed.rowcount != 1:
        raise HTTPException(409, 'there is no open review for this task')
    row = task(db, conv_id)
    if approved:
        await report(runtime, row)
    else:
        await tell(runtime, row['implementer_id'],
                   f"Changes requested; round {row['round']}: {body.findings}. "
                   'Address these findings, then call request_review again.',
                   source=(actor.attachment_id, actor.conv_id))
        handed_to(runtime, actor.attachment_id, row['implementer_id'])
    await runtime.broadcast_all(ConversationsChangedEvent())
    return task(db, conv_id)
