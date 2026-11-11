"""Re-pin an open review and bind subsequent verdicts to its current commits."""

import asyncio
import json
import os
import time

from fastapi import HTTPException

from .contracts import ConversationsChangedEvent
from .git_fence import mirror_branch_ref
from .line_worktree import line_cwd, rev
from .orchestrator_notices import report, tell
from .orchestrator_revive import reviewer_is_live, revive_reviewer, staffed_by_preset
from .orchestrator_sha_check import flag
from .review_worktrees import ReviewError
from .review_install_sandbox import DependencyError
from .task_review_checkout import move_task_review_worktrees, resolve_commit
from .task_workspaces import anchor, moved, tip, workspaces
from .worktree_paths import branch_name


def pairs(repos):
    return {(os.path.realpath(item['repository']), item['sha']) for item in repos}


def review_entries(db, conv_id, row, body):
    """Discover the same requested commits for a first review or a re-pin."""
    cwd = line_cwd(db, conv_id)
    entries = [(item.repository, item.sha) for item in body.repositories or []]
    primary = (row['repositories'] or [{}])[0].get('repository')
    if not entries and not body.sha and workspaces(db, conv_id):
        entries = [(repo, head) for repo, head in moved(db, conv_id)]
        real = {os.path.realpath(repo) for repo, _head in entries}
        for space in workspaces(db, conv_id) if entries else ():
            if primary and os.path.realpath(space['repository']) == os.path.realpath(primary) \
                    and os.path.realpath(primary) not in real:
                entries.append((primary, tip(space, conv_id)))
    if not entries:
        single = mirror_branch_ref(cwd or '', conv_id, branch_name(cwd or ''))
        sha = body.sha or single or rev(cwd or '', 'rev-parse', 'HEAD')
        if not sha:
            raise HTTPException(409, 'task has no commit to review')
        entries = [('', sha)]
    return entries


async def repin(runtime, row, body, entries):
    db, conv_id = runtime.db, row['conv_id']
    try:
        resolved = await asyncio.to_thread(
            lambda: [resolve_commit(db, conv_id, repo, sha) for repo, sha in entries])
        requested = {(os.path.realpath(repo), sha) for repo, sha in resolved}
        if len(requested) != len(entries):
            raise ReviewError(422, 'each repository may appear once in a review')
        if requested == pairs(row['repositories']):
            return False
        checkouts = await asyncio.to_thread(move_task_review_worktrees, db, conv_id, entries,
                                            row['repositories'][0]['repository'])
    except ReviewError as exc:
        if isinstance(exc, DependencyError):
            # The checkout may already have moved; no verdict may use the old SHA.
            db._exec("UPDATE task_reviews SET status='implementing' WHERE conv_id=?", (conv_id,))
            message = f"{exc.detail}. Review stopped; retry request_review after fixing it."
            from .orchestrator_notices import notify_root
            await notify_root(runtime, row, message)
            if row.get("reviewer_id"):
                await tell(runtime, row["reviewer_id"], message)
        raise HTTPException(exc.status_code, exc.detail) from exc
    await asyncio.to_thread(anchor, db, conv_id)
    old = '; '.join(f"{x['repository']} {x['sha']}" for x in row['repositories'])
    new = '; '.join(f"{x['repository']} {x['sha']}" for x in checkouts)
    db._exec('INSERT INTO task_review_repins VALUES(?,?,?,?)', (conv_id, old, new, time.time()))
    db._exec('UPDATE task_reviews SET sha=?,repositories=?,review_worktree=?,what=?,location=?, '
             'repin_required=1,report_id=NULL,reviewer_restarts=0 WHERE conv_id=?',
             (checkouts[0]['sha'], json.dumps(checkouts), checkouts[0]['path'],
              body.what, body.where, conv_id))
    from .orchestrator_store import task
    updated = task(db, conv_id)
    if staffed_by_preset(updated):
        if reviewer_is_live(db, updated):
            await tell(runtime, updated['reviewer_id'],
                       f'Review SHA changed from {old} to {new}. You must review the new commits '
                       'and name their SHA (or all repositories and SHAs) in review_verdict.')
        else:
            await revive_reviewer(runtime, updated)
    await report(runtime, updated)
    await runtime.broadcast_all(ConversationsChangedEvent())
    await flag(runtime, updated, f"{body.what} {body.where}")
    return True


def verdict_matches(row, body):
    current = pairs(row['repositories'])
    if body.repositories is not None:
        given = {(os.path.realpath(x.repository), x.sha) for x in body.repositories}
        return len(given) == len(body.repositories) and given == current
    if body.sha is not None:
        return len(current) == 1 and body.sha == row['sha']
    return not row['repin_required']
