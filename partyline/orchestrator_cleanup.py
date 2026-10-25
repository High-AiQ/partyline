"""Detach shipped tasks, and optionally archive their retained history."""

import asyncio
import logging
import os

from .contracts import ConversationsChangedEvent
from .line_process_routes import detach_attachment
from .line_subtree import archive_line
from .line_worktree import _git, line_cwd, repo_and_worktree, rev
from .git_fence import mirror_branch_ref
from .worktree_paths import branch_name
from .orchestrator_notices import report
from .orchestrator_store import task
from .orchestrator_wait import resume_expired
from .review_worktrees import prune_review_worktrees
from .scratch_worktrees import prune_scratch_worktrees
from .task_workspaces import tip as workspace_tip, workspaces
from .worktree_lifecycle import archive_worktree_if_safe, worktree_state

logger = logging.getLogger(__name__)


def shipped(db, row):
    if not row['sha']:
        return False
    cwd = line_cwd(db, row['root_id'])
    if not cwd:
        return False
    # Parent HEAD is the integration authority, not the task's own branch.
    task_cwd = line_cwd(db, row['conv_id']) or ''
    tip = mirror_branch_ref(task_cwd, row['conv_id'], branch_name(task_cwd)) or rev(
        task_cwd, 'rev-parse', 'HEAD')
    own = os.path.realpath(repo_and_worktree(cwd)[0] or cwd)
    # Each reviewed commit must be in its own repository's HEAD: the root's for
    # the line's repository, the named repository's for the others.
    checks = [(cwd if os.path.realpath(item['repository']) == own else item['repository'], item['sha'])
              for item in row['repositories']] or [(cwd, row['sha'])]
    spaces = workspaces(db, row['conv_id'])
    # Work newer than the approved SHA, in any clone, is not shipped.
    pairs = [*([(cwd, tip)] if tip else []), *checks,
             *[(w['repository'], t) for w in spaces if (t := workspace_tip(w, row['conv_id']))]]
    return (bool(tip) or bool(spaces)) and all(
        os.path.isdir(where)
        and _git('merge-base', '--is-ancestor', sha, 'HEAD', cwd=where).returncode == 0
        for where, sha in pairs)


async def tick(runtime):
    db = runtime.db
    rows = db._exec("SELECT t.* FROM task_reviews t JOIN conversations c ON c.id=t.conv_id "
                    'WHERE c.archived_at IS NULL').fetchall()
    changed = False
    for record in rows:
        row = task(db, record['conv_id'])
        await report(runtime, row)
        await resume_expired(runtime, row)
        if row['status'] not in ('approved', 'done'):
            continue
        if not await asyncio.to_thread(shipped, db, row):
            continue
        # Never detach or discard work newer than the approved SHA.
        state = await asyncio.to_thread(worktree_state, db, db.get_conversation(row['conv_id']))
        if state is None or not state['clean'] or not state['merged']:
            continue
        db._exec('UPDATE task_reviews SET merged=1 WHERE conv_id=?', (row['conv_id'],))
        for ident in (row['implementer_id'], row['reviewer_id']):
            att = db.get_attachment(ident) if ident else None
            if att and att['status'] in ('starting', 'running'):
                if getattr(runtime, 'presence', None) and runtime.presence.is_working(ident):
                    continue
                await detach_attachment(runtime, ident, survivors=False)
        if db.get_setting('auto_clean_task_history') != 'true':
            continue
        if any(att['status'] in ('starting', 'running') for att in db.list_attachments(row['conv_id'])):
            continue
        removed, reason = await asyncio.to_thread(archive_worktree_if_safe, db, row['conv_id'])
        if reason or not removed:
            continue
        await archive_line(runtime, row['conv_id'])
        await asyncio.to_thread(prune_review_worktrees, db, row['conv_id'])
        await asyncio.to_thread(prune_scratch_worktrees, db, row['conv_id'])
        changed = True
    if changed:
        await runtime.broadcast_all(ConversationsChangedEvent())


async def run(runtime):
    while True:
        try:
            await tick(runtime)
        except Exception:
            logger.exception('task maintenance failed; retrying next tick')
        await asyncio.sleep(30)
