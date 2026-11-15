"""Resolve ordered integration batches and brief their reviewer-free suite runner."""

import json
import re

from fastapi import HTTPException

from .line_worktree import line_cwd, rev
from .orchestrator_share_ref import _commit
from .orchestrator_store import task
from .review_scope import _named
from .task_workspaces import anchor, repositories_under, workspaces

SUITE = (
    'Suite run: no reviewer. In the selected repository worktree, create an integration branch '
    'from current main (fetch main first), then cherry-pick resolved batch commits in order. '
    'Report conflicts you cannot resolve trivially; for version-number conflicts keep the batch '
    'numbers the captain gives in the goal. Run every suite the repository has, following its '
    'AGENTS.md. For partyline run ./scripts/capped-test, uv run --locked coverage report (>=90%), '
    'the full frontend npm run verify then npm run build, node --test partyline_chrome/*.test.js, '
    'and all e2e suites (tests/ui/); run frontend builds and backend tests sequentially. '
    'End with deliver(what, where): name the integration branch and SHA, pass or fail per suite, '
    'and map every failure to tasks whose changed files the failing test touches. State that '
    'attribution is best-effort, including unknown ownership. Do not push or open the PR. '
    'After a pass the captain pushes and opens the PR from the integration branch; after failures '
    'the captain reopens responsible tasks or creates fixes, then starts another suite run or '
    'reopens this suite line with new SHAs. ')


def resolve_batch(db, root_id, repository, batch):
    """Resolve only accepted task SHAs within this root and this repository."""
    repos = [(repo, root_id) for repo in repositories_under(line_cwd(db, root_id) or '')]
    hit = _named(repos, repository)
    if not hit:
        raise HTTPException(422, 'suite repository must be one of the root workspace repositories')
    repository = hit[0]
    resolved = []
    for name in batch:
        rows = db._exec('SELECT conv_id FROM task_reviews WHERE root_id=? AND (conv_id=? OR tag=?)',
                        (root_id, name, name)).fetchall()
        if rows:
            row = task(db, rows[0]['conv_id'])
            entries = [(item['repository'], item) for item in row['repositories']]
            selected = _named(entries, repository)
            if row['status'] not in ('approved', 'done') or not row['sha'] or not selected:
                raise HTTPException(422, f'batch task {name} has no accepted SHA for this repository')
            sha = selected[1]['sha']
            source = row['conv_id']
        else:
            if not re.fullmatch(r'[0-9a-f]{4,64}', name):
                raise HTTPException(422, f'unknown batch task or commit SHA: {name}')
            sha, source = name, None
        resolved.append({'sha': _commit(repository, sha), 'task': source})
    return repository, resolved


def save_batch(db, conv_id, repository, batch):
    db._exec('UPDATE task_reviews SET suite_repository=?,suite_batch=? WHERE conv_id=?',
             (repository, json.dumps(batch), conv_id))


def suite_brief(row):
    commits = ', '.join(f"{item['sha']} (task {item['task'] or 'explicit SHA'})"
                        for item in row['suite_batch'])
    return f"{SUITE}Repository: {row['suite_repository']}. Ordered batch: {commits}. "


def record_integration(db, row):
    """Follow the runner's integration branch in the private mirror and keep its tip alive."""
    space = next((item for item in workspaces(db, row['conv_id'])
                  if item['repository'] == row['suite_repository']), None)
    if space is None:
        raise HTTPException(409, 'suite repository has no workspace')
    branch = rev(space['path'], 'symbolic-ref', '--short', 'HEAD')
    if not branch:
        raise HTTPException(409, 'suite delivery requires a named integration branch')
    db._exec('UPDATE task_workspaces SET branch=? WHERE conv_id=? AND repository=?',
             (branch, row['conv_id'], space['repository']))
    from .task_workspaces import tip
    space['branch'] = branch
    sha = tip(space, row['conv_id'])
    if not sha:
        raise HTTPException(409, 'integration branch has no commit')
    anchor(db, row['conv_id'])
    entries = [{'repository': space['repository'], 'sha': sha, 'path': space['path']}]
    db._exec('UPDATE task_reviews SET sha=?,repositories=? WHERE conv_id=?',
             (sha, json.dumps(entries), row['conv_id']))
