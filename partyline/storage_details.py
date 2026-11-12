"""On-demand inventory for kept worktrees and idle, open lines."""

import time

from pydantic import BaseModel

from .storage_worktrees import candidates, protected
from .storage_survey import Budget, inside
from .worktree_storage import kept_reason, repositories


class StoragePath(BaseModel):
    path: str
    reason: str
    size_bytes: int


class IdleLine(BaseModel):
    id: str
    name: str
    idle_since: float
    size_bytes: int


class StorageDetails(BaseModel):
    kept: list[StoragePath]
    idle_lines: list[IdleLine]


class CleanupKept(BaseModel):
    path: str
    reason: str
    size_bytes: int = 0


class CleanupResult(BaseModel):
    removed: list[str]
    freed_bytes: int
    skipped: list[CleanupKept]


def details(db, now=None):
    now = time.time() if now is None else now
    budget = Budget()
    kept, sizes, counted = [], {}, {}
    for root, path, owner in candidates(db):
        size = budget.size(path)
        if owner:
            previous = counted.setdefault(owner['id'], [])
            if not any(inside(path, parent) for parent in previous):
                sizes[owner['id']] = sizes.get(owner['id'], 0) + size
                previous.append(path)
        if owner and not owner.get('archived_at'):
            continue
        nested = repositories(path)
        reason = protected(db, path, owner) or kept_reason(db, root, path) or (
            'contains nested repositories: ' + ', '.join(nested) if nested else
            'awaiting cleanup; changes will be saved in recovery refs')
        kept.append(StoragePath(path=path, reason=reason, size_bytes=size))
    idle = []
    for line in db.list_conversations():
        if any(att['status'] in ('starting', 'running') for att in db.list_attachments(line['id'])):
            continue
        latest = db._exec('SELECT MAX(created_at) latest FROM messages WHERE conv_id=?',
                          (line['id'],)).fetchone()['latest']
        since = max(line['created_at'], latest or 0)
        if now - since > 14 * 86400:
            idle.append(IdleLine(id=line['id'], name=line['name'], idle_since=since,
                                 size_bytes=sizes.get(line['id'], 0)))
    return StorageDetails(kept=kept, idle_lines=idle)
