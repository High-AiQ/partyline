"""Expand accepted tasks into their complete per-repository commit ranges."""

from fastapi import HTTPException

from .line_worktree import _git, rev
from .suite_workspaces import workspace_for
from .task_workspaces import workspaces


def task_commits(db, row, repository, accepted):
    space = workspace_for(workspaces(db, row['conv_id']), repository)
    if not space or not space.get('base_sha'):
        raise HTTPException(422, f"batch task {row['conv_id']} has no recorded base for {repository}; "
                            'supply explicit commit SHAs in order')
    base = space['base_sha']
    if _git('merge-base', '--is-ancestor', base, accepted, cwd=repository).returncode:
        raise HTTPException(422, f"batch task {row['conv_id']} base is not an ancestor of its accepted "
                            f'commit in {repository}; supply explicit commit SHAs in order')
    from .worktree_lifecycle import _default_branch
    default = _default_branch(repository)
    excluded = [base]
    if default:
        excluded.append(default)
        if default.startswith('origin/'):
            local = rev(repository, 'rev-parse', '--verify',
                        f"refs/heads/{default.removeprefix('origin/')}^{{commit}}")
            if local:
                excluded.append(local)
    result = _git('rev-list', '--reverse', '--topo-order', '--no-merges', accepted,
                  '--not', *excluded, cwd=repository)
    if result.returncode:
        raise HTTPException(422, f"cannot read batch task {row['conv_id']} range in {repository}")
    return result.stdout.splitlines()
