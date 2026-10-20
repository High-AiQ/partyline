"""Accepting a task that was reviewed across several repositories.

The line's own repository takes the usual fast-forward hand-off; every other
repository's reviewed commit is verified to exist there and recorded, since
its branch is not the line's to move.
"""

from __future__ import annotations

import os

from fastapi import HTTPException

from .accept_history import record_accept
from .line_worktree import line_cwd, repo_and_worktree, rev
from .review_worktrees import prune_accepted_review
from .worktree_paths import branch_name


def plan(db, conv_id: str, task_row: dict, sha: str):
    """``(sha for the line's repository or None, [other reviewed repositories])``.

    A reviewed commit that is no longer in its repository refuses the accept (409).
    """
    entries = (task_row or {}).get('repositories') or []
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


def settle_unmoved(db, conv_id: str, sha: str) -> dict:
    """The accept result when the line's own repository was not part of the review."""
    db._exec("UPDATE conversations SET accepted_sha=? WHERE id=?", (sha, conv_id))
    cwd = line_cwd(db, conv_id) or ''
    return {'branch': branch_name(cwd), 'sha': sha, 'moved': False, 'pruned_reviews': 0,
            'reviewed_sha': None, 'past_review': None,
            'tree_sync': {'ok': True, 'worktree': None, 'detail': ''}}


def record_others(db, conv_id: str, others: list[dict], who: str) -> None:
    for item in others:
        record_accept(db, conv_id, item['sha'], who, [f"repository {item['repository']}"])
        prune_accepted_review(db, conv_id, item['sha'])


def tail(others: list[dict]) -> str:
    return ''.join(f"; {item['repository']} {item['sha'][:12]}" for item in others)
