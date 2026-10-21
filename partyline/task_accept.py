"""Accepting a task that was reviewed across several repositories.

The line's own repository takes the usual fast-forward hand-off; every other
repository's reviewed commit is verified to exist there and recorded, since
its branch is not the line's to move.
"""

from __future__ import annotations

import os
import time

from fastapi import HTTPException

from .contracts import ConversationsChangedEvent
from .accept_history import record_accept
from .line_worktree import _git, line_cwd, repo_and_worktree, rev
from .task_workspaces import tip, workspaces
from .review_worktrees import prune_accepted_review
from .worktree_paths import branch_name


def plan(db, conv_id: str, task_row: dict, sha: str):
    """``(sha for the line's repository or None, [other reviewed repositories])``.

    A reviewed commit that is no longer in its repository refuses the accept (409).
    """
    entries = (task_row or {}).get('repositories') or []
    if task_row and workspaces(db, conv_id):
        # Each reviewed commit is verified and recorded; settle_unmoved moves the task's branches.
        return None, [{'repository': item['repository'], 'sha': item['sha']}
                      for item in entries if item['sha'] != sha and _exists(item)]
    if not entries:
        return sha, []
    own_root = repo_and_worktree(line_cwd(db, conv_id) or '')[0]
    own = os.path.realpath(own_root) if own_root else None
    mine, others = None, []
    for item in entries:
        if own and os.path.realpath(item['repository']) == own:
            mine = item['sha']
        else:
            if rev(item['repository'], 'rev-parse', '--verify', '--quiet',
                   f"{item['sha']}^{{commit}}") is None:
                raise HTTPException(
                    409, f"reviewed commit {item['sha'][:12]} is not in {item['repository']}")
            others.append({'repository': item['repository'], 'sha': item['sha']})
    return mine, others


def _exists(item: dict) -> bool:
    if rev(item['repository'], 'rev-parse', '--verify', '--quiet', f"{item['sha']}^{{commit}}") is None:
        raise HTTPException(409, f"reviewed commit {item['sha'][:12]} is not in {item['repository']}")
    return True


def _ahead(repo: str, old: str, new: str) -> bool:
    return _git('merge-base', '--is-ancestor', old, new, cwd=repo).returncode == 0


def move_branches(db, conv_id: str, entries: list[dict]) -> bool:
    """Fast-forward the task's own `line/<slug>` in each clone to its reviewed commit, where that
    is a plain fast-forward onto a commit the task made. The person's checkout never moves."""
    moved = False
    for item in entries:
        for space in workspaces(db, conv_id):
            repo = space['repository']
            if os.path.realpath(repo) != os.path.realpath(item['repository']):
                continue
            ref = f"refs/heads/{space['branch']}"
            real = rev(repo, 'rev-parse', '--verify', '--quiet', ref)
            head = tip(space, conv_id)
            if (real and head and real != item['sha'] and _ahead(repo, real, item['sha'])
                    and _ahead(repo, item['sha'], head)):
                moved |= _git('update-ref', ref, item['sha'], real, cwd=repo).returncode == 0
    return moved


def settle_unmoved(db, conv_id: str, sha: str, task_row: dict | None = None) -> dict:
    """The accept result when the line's own repository was not part of the review."""
    db._exec("UPDATE conversations SET accepted_sha=? WHERE id=?", (sha, conv_id))
    moved = move_branches(db, conv_id, (task_row or {}).get('repositories') or [])
    prune_accepted_review(db, conv_id, sha)
    cwd = line_cwd(db, conv_id) or ''
    return {'branch': branch_name(cwd), 'sha': sha, 'moved': moved, 'pruned_reviews': 0,
            'reviewed_sha': None, 'past_review': None,
            'tree_sync': {'ok': True, 'worktree': None, 'detail': ''}}


def record_others(db, conv_id: str, others: list[dict], who: str) -> None:
    for item in others:
        record_accept(db, conv_id, item['sha'], who, [f"repository {item['repository']}"])
        prune_accepted_review(db, conv_id, item['sha'])


def tail(others: list[dict]) -> str:
    return ''.join(f"; {item['repository']} {item['sha'][:12]}" for item in others)


async def settle_task(runtime, conv_id: str, task_row: dict | None) -> None:
    """An accepted task is finished: done, settled now, no block or stall left."""
    if not task_row:
        return
    runtime.db._exec(
        "UPDATE task_reviews SET status='done',settled_at=COALESCE(settled_at,?),blocked_at=NULL,"
        'stall_stage=0,stall_notice_id=NULL WHERE conv_id=?', (time.time(), conv_id))
    await runtime.broadcast_all(ConversationsChangedEvent())
