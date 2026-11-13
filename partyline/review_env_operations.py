"""Captain operations for resolving review environment gaps."""

import asyncio
import json
import time

from fastapi import HTTPException
from pydantic import BaseModel, Field

from .orchestrator_notices import notify_root, tell
from .orchestrator_store import require_root, task
from .review_dependencies import provision, sources_for
from .review_environments import Environment, changed_files, entries_for, normalize, repository_key
from .review_scope import ReviewError


class ReviewEnvOperation(BaseModel):
    operation: str
    repository: str = ''
    subpath: str = '.'
    setup: str = Field(default='', max_length=4096)
    test: str = Field(default='', max_length=4096)


async def operate(runtime, actor, root_id, body):
    db = runtime.db
    require_root(db, actor, root_id)
    if actor.kind != 'machine' or not actor.is_lead or actor.conv_id != root_id:
        raise HTTPException(403, 'only the root captain may manage review environments')
    if body.operation == 'list':
        return {'entries': [dict(row) for row in db._exec('SELECT * FROM review_environments').fetchall()]}
    if body.operation not in ('set', 'delete'):
        raise HTTPException(422, 'operation must be list, set or delete')
    try:
        entry = Environment(repository=body.repository, subpath=body.subpath,
                            setup_command=body.setup, test_command=body.test)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    # Remove equivalent URL spellings too; settings identify the repository, not its spelling.
    with db.lock, db.conn:
        rows = db.conn.execute('SELECT repository,subpath FROM review_environments').fetchall()
        for row in rows:
            if (normalize(row['repository']) == normalize(entry.repository)
                    and row['subpath'] == entry.subpath):
                db.conn.execute('DELETE FROM review_environments WHERE repository=? AND subpath=?',
                                (row['repository'], row['subpath']))
        if body.operation == 'set':
            db.conn.execute('INSERT INTO review_environments VALUES(?,?,?,?,?,?)',
                            (entry.repository, entry.subpath, entry.setup_command, entry.test_command,
                             actor.name, time.time()))
    await runtime.post_message(root_id, 'system', 'system',
                               f'review env for {entry.repository}/{entry.subpath} {body.operation} by '
                               f'{actor.name}: setup {entry.setup_command or "(default)"}; '
                               f'test {entry.test_command or "(none)"}')
    if body.operation == 'set':
        await refresh_reviews(runtime, root_id, entry)
    return {'ok': True}


async def refresh_reviews(runtime, root_id, entry):
    db = runtime.db
    rows = db._exec("SELECT conv_id FROM task_reviews WHERE root_id=? AND status='in_review'",
                    (root_id,)).fetchall()
    from .orchestrator_revive import task_lock
    failures = []
    for record in rows:
        async with task_lock(runtime, record['conv_id']):
            row = task(db, record['conv_id'])
            if not row or row['status'] != 'in_review':
                continue
            failures.extend(await refresh_task(runtime, row, entry))
    if failures:
        raise HTTPException(409, 'review environment saved, but setup failed: ' + '; '.join(failures))


async def refresh_task(runtime, row, entry):
    db = runtime.db
    failures = []
    for repo in row['repositories']:
        if repository_key(repo['repository']) != normalize(entry.repository):
            continue
        changed = changed_files(db, row['conv_id'], repo['repository'], repo['sha'])
        selected = [name for name in changed if any(e.subpath == entry.subpath for e in
                    entries_for(db, repo['repository'], [name]))]
        if not selected:
            continue
        try:
            await asyncio.to_thread(provision, repo['path'], sources_for(db, row['conv_id'],
                                    repo['repository']), selected, [entry])
        except ReviewError as exc:
            await notify_root(runtime, row, exc.detail)
            if row['reviewer_id']:
                await tell(runtime, row['reviewer_id'], exc.detail)
            failures.append(f"{row['conv_id']} ({repo['path']}): {exc.detail}")
            continue
        repo['test_commands'] = [{'subpath': e.subpath, 'command': e.test_command}
                                 for e in entries_for(db, repo['repository'], changed)]
        db._exec('UPDATE task_reviews SET repositories=? WHERE conv_id=?',
                 (json.dumps(row['repositories']), row['conv_id']))
        if row['reviewer_id']:
            await tell(runtime, row['reviewer_id'], f"Review environment updated in {repo['path']}/"
                       f"{entry.subpath}. Test command: {entry.test_command or '(none set)'}. "
                       'Continue this review and report what ran.')
    return failures
