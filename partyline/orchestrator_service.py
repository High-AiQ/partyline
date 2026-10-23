"""Structured task lifecycle; task policy is chosen only by the root captain."""

import asyncio
import json
import os
import time
import uuid

from fastapi import HTTPException

from .child_create import create_child
from .contracts import ConversationsChangedEvent
from .hierarchy_contracts import ChildIn
from .line_worktree import line_cwd, rev
from .git_fence import mirror_branch_ref
from .task_workspaces import anchor, moved, tip, workspaces
from .worktree_paths import branch_name
from .review_worktrees import ReviewError
from .task_review_checkout import move_task_review_worktrees
from .orchestrator_notices import handed_to, report, spawn_refused, tell
from .orchestrator_revive import (
    brief_reviewer, reviewer_is_live, revive_reviewer, staffed_by_preset, task_lock)
from .orchestrator_handles import pick_tag
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
        "AND t.status IN ('implementing','idle') AND c.archived_at IS NULL "
        "AND (a.id IS NULL OR (a.status='exited' AND a.cli_session IS NULL)) LIMIT 1",
        (root_id, body.name.strip(), body.goal.strip(), body.implementer, policy)).fetchone()
    if pending:
        conv_id, ident = pending['conv_id'], pending['implementer_id']
    else:
        result = await create_child(runtime, actor, root_id, ChildIn(name=body.name, goal=body.goal),
                                    workspace=True)
        conv_id, ident = result.conversation.id, str(uuid.uuid4())
        db._exec(
            'INSERT INTO task_reviews(conv_id,root_id,implementer_id,implementer_preset,policy,tag,'
            'created_at) VALUES(?,?,?,?,?,?,?)',
            (conv_id, root_id, ident, body.implementer, policy, pick_tag(db, conv_id), time.time()))
    try:
        existing = db.get_attachment(ident)
        if existing:
            await restart(runtime, existing)
        else:
            tag = task(db, conv_id)['tag']
            await spawn(runtime, conv_id, body.implementer, ident,
                        handle=f'impl-{tag}' if tag else None)
    except (HTTPException, ValueError) as exc:
        await spawn_refused(runtime, task(db, conv_id), getattr(exc, 'detail', str(exc)), implementer=True)
        raise
    await tell(runtime, ident,
               f"Implement this task: {body.goal}. Commit on this line's branch (in each repository folder "
               'you change); never push. '
               'Call request_review(sha, what, where) when ready. The server owns review staffing.')
    await runtime.broadcast_all(ConversationsChangedEvent())
    return task(db, conv_id)


async def request_review(runtime, actor, conv_id, body):
    db = runtime.db
    row = require_task(db, actor, conv_id)
    # A task lock spans worktree creation, admission and notification: duplicate
    # calls cannot spawn two reviewers or produce two terminal reports.
    async with task_lock(runtime, conv_id):
        row = require_task(db, actor, conv_id)
        if row['status'] in ('approved', 'done'):
            await report(runtime, row)
            return task(db, conv_id)
        if row['status'] == 'in_review':
            # Asking again revives a reviewer that died after admission.
            if staffed_by_preset(row) and not reviewer_is_live(db, row):
                db._exec('UPDATE task_reviews SET reviewer_restarts=0 WHERE conv_id=?', (conv_id,))
                try:
                    await revive_reviewer(runtime, row)
                except (HTTPException, ValueError) as exc:
                    await spawn_refused(runtime, row, getattr(exc, 'detail', str(exc)))
                    raise
            return task(db, conv_id)
        from .orchestrator_stall import resume
        resume(db, conv_id)
        cwd = line_cwd(db, conv_id)
        entries = [(item.repository, item.sha) for item in body.repositories or []]
        primary = (row['repositories'] or [{}])[0].get('repository')
        if not entries and not body.sha and workspaces(db, conv_id):
            # Every repository whose task branch moved, and the one reviewed before.
            entries = [(repo, head) for repo, head in moved(db, conv_id)]
            real = {os.path.realpath(repo) for repo, _head in entries}
            for space in workspaces(db, conv_id) if entries else ():
                if primary and os.path.realpath(space['repository']) == os.path.realpath(primary) \
                        and os.path.realpath(primary) not in real:
                    entries.append((primary, tip(space, conv_id)))
        if not entries:
            single = mirror_branch_ref(cwd or "", conv_id, branch_name(cwd or ""))
            sha = body.sha or single or rev(cwd or '', 'rev-parse', 'HEAD')
            if not sha:
                raise HTTPException(409, 'task has no commit to review')
            entries = [('', sha)]
        try:
            checkouts = await asyncio.to_thread(
                move_task_review_worktrees, db, conv_id, entries, primary)
        except ReviewError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc
        await asyncio.to_thread(anchor, db, conv_id)
        db._exec(
            'UPDATE task_reviews SET sha=?,review_worktree=?,repositories=?,what=?,location=?, '
            "findings='', "
            'round=CASE WHEN round=0 THEN 1 ELSE round END,reviewer_restarts=0 WHERE conv_id=?',
            (checkouts[0]['sha'], checkouts[0]['path'], json.dumps(checkouts),
             body.what, body.where, conv_id))
        row = task(db, conv_id)
        if row['policy'] not in ('none', 'captain'):
            try:
                reviewer = await ensure_reviewer(runtime, row)
            except (HTTPException, ValueError) as exc:
                await spawn_refused(runtime, row, getattr(exc, 'detail', str(exc)))
                raise
        settled = row['policy'] == 'none'
        db._exec('UPDATE task_reviews SET status=?,settled_at=?,reopen_noticed=0 WHERE conv_id=?',
                 ('done' if settled else 'in_review', time.time() if settled else None, conv_id))
        row = task(db, conv_id)
        if row['policy'] not in ('none', 'captain'):
            await brief_reviewer(runtime, row, reviewer)
            handed_to(runtime, row['implementer_id'], reviewer['id'])
        await report(runtime, row)
        await runtime.broadcast_all(ConversationsChangedEvent())
        return task(db, conv_id)


async def review_verdict(runtime, actor, conv_id, body):
    db = runtime.db
    row = require_task(db, actor, conv_id, reviewer=True)
    approved = body.verdict == 'approve'
    changed = db._exec(
        'UPDATE task_reviews SET status=?,findings=?,previous_findings=CASE WHEN ? THEN previous_findings '
        'ELSE ? END,round=round+?,reviewer_restarts=0,'
        "settled_at=?,reopen_noticed=0 WHERE conv_id=? AND status='in_review'",
        ('approved' if approved else 'implementing', body.findings, approved, body.findings,
         int(not approved), time.time() if approved else None, conv_id))
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
