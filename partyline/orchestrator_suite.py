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
    'Suite run: no reviewer. In each selected repository worktree, create an integration branch '
    'from current main (fetch main first), then cherry-pick that repository\'s resolved batch '
    'commits in order. '
    'Report conflicts you cannot resolve trivially; for version-number conflicts keep the batch '
    'numbers the captain gives in the goal. Run every suite the repository has, following its '
    'AGENTS.md. Run one combined end-to-end run across all selected trees served together. '
    'For partyline run ./scripts/capped-test, uv run --locked coverage report (>=90%), '
    'the full frontend npm run verify then npm run build, node --test partyline_chrome/*.test.js, '
    'and all e2e suites (tests/ui/); run frontend builds and backend tests sequentially. '
    'End with deliver(what, where), optionally passing repositories=[{repository, sha}, ...]: '
    'name each integration branch '
    'and SHA, pass or fail per suite, '
    'and map every failure to tasks whose changed files the failing test touches. State that '
    'attribution is best-effort, including unknown ownership. Do not push or open the PR. '
    'After a pass the captain pushes and opens the PR from the integration branch; after failures '
    'the captain reopens responsible tasks or creates fixes, then starts another suite run or '
    'reopens this suite line with new SHAs. During long runs, post short progress beats to your line '
    '(N/M suites done, failures so far), not only at the end. ')


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


def resolve_repositories(db, root_id, body):
    inputs = body.repositories or [body]
    resolved = []
    for item in inputs:
        repository, batch = resolve_batch(db, root_id, item.repository, item.batch)
        if any(entry['repository'] == repository for entry in resolved):
            raise HTTPException(422, 'each repository may appear once')
        resolved.append({'repository': repository, 'batch': batch})
    return resolved


def save_repositories(db, conv_id, repositories):
    # Keep the original single-repository response fields for older clients.
    first = repositories[0]
    entries = [{key: item[key] for key in ('repository', 'batch')} for item in repositories]
    db._exec('UPDATE task_reviews SET suite_repository=?,suite_batch=?,suite_repositories=? WHERE conv_id=?',
             (first['repository'], json.dumps(first['batch']), json.dumps(entries), conv_id))


def suite_brief(row):
    parts = [SUITE]
    for repo in row['suite_repositories']:
        commits = ', '.join(f"{item['sha']} (task {item['task'] or 'explicit SHA'})"
                            for item in repo['batch'])
        parts.append(f"Repository: {repo['repository']}. Worktree: {repo.get('path')}. "
                     f"Ordered batch: {commits}. ")
    return ''.join(parts)


def suite_goal(goal, row):
    locations = '\n'.join(f"- {item['repository']}: {item.get('path')}" for item in row['suite_repositories'])
    return (f'{goal.strip()}\n\nSuite worktrees:\n{locations}\n'
            'Run every repository\'s suites and one combined end-to-end run across all trees.')


def record_integration(db, row, repositories=None):
    """Follow the runner's integration branch in the private mirror and keep its tip alive."""
    from .task_workspaces import tip
    selected = [item['repository'] for item in row['suite_repositories']]
    reported = {}
    for item in repositories or []:
        hit = _named([(repo, repo) for repo in selected], item.repository)
        if not hit or hit[0] in reported:
            raise HTTPException(422, 'delivery repositories must name each suite repository once')
        reported[hit[0]] = item.sha
    if repositories is not None and set(reported) != set(selected):
        raise HTTPException(422, 'delivery repositories must name every suite repository')
    spaces = {item['repository']: item for item in workspaces(db, row['conv_id'])}
    entries, branches = [], []
    for repository in selected:
        space = spaces.get(repository)
        if space is None:
            raise HTTPException(409, f'suite repository has no workspace: {repository}')
        branch = rev(space['path'], 'symbolic-ref', '--short', 'HEAD')
        if not branch:
            raise HTTPException(409, 'suite delivery requires a named integration branch')
        sha = tip(dict(space, branch=branch), row['conv_id'])
        if not sha:
            raise HTTPException(409, 'integration branch has no commit')
        if repository in reported and _commit(repository, reported[repository]) != sha:
            raise HTTPException(409, f'delivered SHA does not match integration branch in {repository}')
        branches.append((branch, row['conv_id'], repository))
        entries.append({'repository': repository, 'sha': sha, 'path': space['path']})
    for branch in branches:
        db._exec('UPDATE task_workspaces SET branch=? WHERE conv_id=? AND repository=?', branch)
    anchor(db, row['conv_id'])
    db._exec('UPDATE task_reviews SET sha=?,repositories=? WHERE conv_id=?',
             (entries[0]['sha'], json.dumps(entries), row['conv_id']))
