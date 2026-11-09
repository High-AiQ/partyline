"""Structured task lifecycle; task policy is chosen only by the root captain."""

import asyncio
import json
import logging
import time
import uuid

from fastapi import HTTPException

from .child_create import create_child
from .contracts import ConversationsChangedEvent
from .hierarchy_contracts import TaskChildIn
from .task_workspaces import anchor, workspaces
from .review_worktrees import ReviewError
from .task_review_checkout import move_task_review_worktrees
from .orchestrator_notices import handed_to, report, spawn_refused, tell
from .orchestrator_sha_check import flag
from .orchestrator_revive import (
    brief_reviewer, reviewer_is_live, revive_reviewer, staffed_by_preset, task_lock)
from .orchestrator_repin import repin, review_entries, verdict_matches
from .orchestrator_handles import pick_tag
from .memory_live_raise import check_task_memory
from .orchestrator_staff import ensure_reviewer, restart, spawn
from .orchestrator_store import (
    EXPRESS_BRIEF, EXPRESS_NO_REVIEW, preset, require_override, require_root, require_task, task,
    validate_policy)


logger = logging.getLogger(__name__)


async def create_task(runtime, actor, root_id, body):
    # Serialize retries through placement, staffing and the response snapshot.
    async with task_lock(runtime, f'create:{root_id}'):
        return await _create_task(runtime, actor, root_id, body)


async def _create_task(runtime, actor, root_id, body):
    db = runtime.db
    root = require_root(db, actor, root_id)
    preset(db, body.implementer)
    check_task_memory(db, actor, body.memory_limit)
    if body.mode == 'express':
        if body.review not in (None, 'none'):
            raise HTTPException(422, "an express task has no review: omit review or pass 'none'")
        policy = 'none'
    else:
        policy = validate_policy(db, body.review or root['default_review_policy'])
    existing_line = db._exec(
        'SELECT id FROM conversations WHERE parent_id=? AND name=? AND archived_at IS NULL',
        (root_id, body.name.strip())).fetchone()
    pending = task(db, existing_line['id']) if existing_line else None
    if existing_line:
        if (not pending or pending['goal'] != body.goal.strip()
                or pending['implementer_preset'] != body.implementer or pending['policy'] != policy
                or pending['mode'] != body.mode):
            raise HTTPException(409, f"line {existing_line['id']} already uses this task name; "
                                'inspect it or choose a different name for new work')
        att = db.get_attachment(pending['implementer_id'])
        if (pending['status'] not in ('implementing', 'idle') or
                (att and (att['status'] != 'exited' or att['cli_session']))):
            return task(db, pending['conv_id'], visibility=True)
    creation_error = None
    if pending:
        conv_id, ident = pending['conv_id'], pending['implementer_id']
    else:
        base = 'upstream' if body.base == 'upstream' else 'checkout'
        conv_id, ident = None, str(uuid.uuid4())

        def reserve(conv):
            nonlocal conv_id
            conv_id = conv['id']
            db._exec(
                'INSERT INTO task_reviews(conv_id,root_id,implementer_id,implementer_preset,policy,tag,'
                'created_at,mode) VALUES(?,?,?,?,?,?,?,?)',
                (conv_id, root_id, ident, body.implementer, policy, pick_tag(db, conv_id), time.time(),
                 body.mode))

        try:
            await create_child(runtime, actor, root_id,
                               TaskChildIn(name=body.name, goal=body.goal, base=base),
                               workspace=True, on_ready=reserve)
        except (HTTPException, ValueError, OSError) as exc:
            if conv_id is None:
                raise  # placement never completed; no task was reserved
            creation_error = str(getattr(exc, 'detail', exc))
            logger.exception('task creation announcement failed for %s', conv_id)
    spawn_failed = False
    try:
        existing = db.get_attachment(ident)
        if existing:
            if body.memory_limit and existing['status'] == 'exited':
                db._exec('UPDATE attachments SET memory_limit=? WHERE id=?',
                         (body.memory_limit, ident))
                existing = db.get_attachment(ident)
            await restart(runtime, existing)
        else:
            tag = task(db, conv_id)['tag']
            await spawn(runtime, conv_id, body.implementer, ident,
                        handle=f'impl-{tag}' if tag else None, memory_limit=body.memory_limit)
    except (HTTPException, ValueError, OSError) as exc:
        spawn_failed = True
        creation_error = str(getattr(exc, 'detail', exc))
        # Creation committed: return its identity even when staffing is refused.
        # Retrying the same assignment will retry this reservation, never fork it.
        try:
            await spawn_refused(runtime, task(db, conv_id), creation_error, implementer=True)
        except (HTTPException, ValueError, OSError):
            logger.exception('task creation refusal notice failed for %s', conv_id)
    if not spawn_failed:
        try:
            await tell(runtime, ident, f'Implement this task: {body.goal}. ' + (
                EXPRESS_BRIEF if body.mode == 'express' else
                "Commit on this line's branch (in each repository folder you change); never push. "
                'Call request_review(sha, what, where) when ready. The server owns review staffing.'))
            await runtime.broadcast_all(ConversationsChangedEvent())
        except (HTTPException, ValueError, OSError) as exc:
            creation_error = str(getattr(exc, 'detail', exc))
            logger.exception('task creation delivery failed for %s', conv_id)
    row = task(db, conv_id, visibility=True)
    row['creation_error'] = creation_error
    # The task folder already holds a worktree of every repository under the
    # captain's folder; the review entry waits for one, so say so now.
    if not row['repositories']:
        row['repositories'] = [
            {'repository': item['repository'], 'sha': item['base_sha'], 'path': item['path']}
            for item in workspaces(db, conv_id)]
    return row


async def request_review(runtime, actor, conv_id, body):
    db = runtime.db
    row = require_task(db, actor, conv_id)
    if row['mode'] == 'express':
        raise HTTPException(409, EXPRESS_NO_REVIEW)
    # A task lock spans worktree creation, admission and notification: duplicate
    # calls cannot spawn two reviewers or produce two terminal reports.
    async with task_lock(runtime, conv_id):
        row = require_task(db, actor, conv_id)
        if row['status'] in ('approved', 'done'):
            await report(runtime, row)
            return task(db, conv_id, visibility=True)
        if row['status'] == 'in_review':
            entries = await asyncio.to_thread(review_entries, db, conv_id, row, body)
            if await repin(runtime, row, body, entries):
                return task(db, conv_id, visibility=True)
            # Asking again revives a reviewer that died after admission.
            if staffed_by_preset(row) and not reviewer_is_live(db, row):
                db._exec('UPDATE task_reviews SET reviewer_restarts=0 WHERE conv_id=?', (conv_id,))
                try:
                    await revive_reviewer(runtime, row)
                except (HTTPException, ValueError) as exc:
                    await spawn_refused(runtime, row, getattr(exc, 'detail', str(exc)))
                    raise
            return task(db, conv_id, visibility=True)
        from .orchestrator_stall import resume
        await asyncio.to_thread(resume, db, conv_id)
        entries = await asyncio.to_thread(review_entries, db, conv_id, row, body)
        primary = (row['repositories'] or [{}])[0].get('repository')
        try:
            checkouts = await asyncio.to_thread(
                move_task_review_worktrees, db, conv_id, entries, primary)
        except ReviewError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc
        await asyncio.to_thread(anchor, db, conv_id)
        db._exec(
            'UPDATE task_reviews SET sha=?,review_worktree=?,repositories=?,what=?,location=?, '
            "findings='',overridden_by=NULL, "
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
        await flag(runtime, row, f"{body.what} {body.where}")
        return task(db, conv_id, visibility=True)


async def review_verdict(runtime, actor, conv_id, body):
    async with task_lock(runtime, conv_id):
        return await _review_verdict(runtime, actor, conv_id, body)


async def _review_verdict(runtime, actor, conv_id, body):
    db = runtime.db
    captain = None
    if body.override:
        row, captain = require_override(db, actor, conv_id)
    else:
        row = require_task(db, actor, conv_id, reviewer=True)
    if row['status'] == 'in_review' and not verdict_matches(row, body):
        raise HTTPException(409, f"stale or missing review SHA; review current SHA {row['sha']} "
                            'and name all current repository SHAs in the verdict')
    approved = body.verdict == 'approve'
    changed = db._exec(
        'UPDATE task_reviews SET status=?,findings=?,previous_findings=CASE WHEN ? THEN previous_findings '
        'ELSE ? END,round=round+?,reviewer_restarts=0,'
        'report_id=CASE WHEN ? THEN report_id ELSE NULL END,'
        "settled_at=?,reopen_noticed=0,overridden_by=? WHERE conv_id=? AND status='in_review'",
        ('approved' if approved else 'implementing', body.findings, approved, body.findings,
         int(not approved), approved, time.time() if approved else None,
         captain['name'] if captain else None, conv_id))
    if changed.rowcount != 1:
        raise HTTPException(409, 'there is no open review for this task')
    row = task(db, conv_id)
    if captain:
        # The superseded reviewer hears it once, privately, from the override itself.
        await tell(runtime, row['reviewer_id'],
                   f"Captain @{captain['name']} overrode the review with a '{body.verdict}' "
                   f"verdict: {body.findings}")
    if approved:
        await report(runtime, row)
    else:
        await tell(runtime, row['implementer_id'],
                   f"Changes requested; round {row['round']}: {body.findings}. "
                   'Address these findings, then call request_review again.',
                   source=(actor.attachment_id, actor.conv_id))
        handed_to(runtime, actor.attachment_id, row['implementer_id'])
        await flag(runtime, row, body.findings)
    await runtime.broadcast_all(ConversationsChangedEvent())
    return task(db, conv_id)
