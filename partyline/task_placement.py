"""Repair missing task workspaces without switching or writing a shared checkout."""

import os
import subprocess

from .line_worktree import WORKTREES_DIR, _git, line_cwd, repo_root, rev
from .suite_workspaces import workspace_for
from .task_workspaces import WorkspaceUnavailable, _add, place_task, workspaces
from .worktree_paths import branch_name
from .worktree_recovery import add_worktree, remove_registration


def ensure_placement(db, row, selected=None):
    conv_id = row['conv_id']
    spaces = workspaces(db, conv_id)
    cwd = (db.get_conversation(conv_id) or {}).get('cwd')
    placed = False
    if not cwd and not spaces:
        placed = bool(place_task(db, row['root_id'], conv_id))
        spaces = workspaces(db, conv_id)
        cwd = (db.get_conversation(conv_id) or {}).get('cwd')
    missing = [entry['repository'] for entry in selected or []
               if not (space := workspace_for(spaces, entry['repository']))
               or not os.path.isfile(os.path.join(space['path'], '.git'))]
    if not missing:
        return placed
    folder = line_cwd(db, row['root_id']) or ''
    folder = os.path.realpath(repo_root(folder) or folder)
    managed = os.path.join(folder, WORKTREES_DIR)
    if not cwd or os.path.dirname(os.path.realpath(cwd)) != managed:
        raise WorkspaceUnavailable(f'workspace for {missing[0]}: task has no managed workspace; '
                                   'ask the root captain to recreate it')
    made = []
    try:
        for repository in missing:
            previous = workspace_for(spaces, repository)
            path = previous['path'] if previous else os.path.normpath(
                os.path.join(cwd, os.path.relpath(repository, folder)))
            if os.path.commonpath((os.path.realpath(path), os.path.realpath(cwd))) != os.path.realpath(cwd):
                raise WorkspaceUnavailable(f'workspace for {repository}: path is outside the task workspace')
            branch = previous['branch'] if previous else branch_name(cwd)
            head = previous['base_sha'] if previous else rev(repository, 'rev-parse', 'HEAD')
            if not head:
                raise WorkspaceUnavailable(f'workspace for {repository}: repository has no HEAD commit')
            if os.path.exists(path):
                top = rev(path, 'rev-parse', '--show-toplevel')
                if (os.path.realpath(top or '') != os.path.realpath(path)
                        or not workspace_for([{'repository': repo_root(path)}], repository)):
                    raise WorkspaceUnavailable(f'workspace for {repository}: {path} already exists; '
                                               'preserve its contents before repairing placement')
                branch = rev(path, 'symbolic-ref', '--short', 'HEAD')
                if not branch:
                    raise WorkspaceUnavailable(f'workspace for {repository}: {path} has detached HEAD')
                made.append((repository, path, branch, head, False, False))
                continue
            existing = rev(repository, 'rev-parse', '--verify', f'refs/heads/{branch}')
            if existing:
                try:
                    result = add_worktree(repository, path, path, branch, git=_git)
                except (OSError, subprocess.SubprocessError) as exc:
                    raise WorkspaceUnavailable(f'workspace for {repository}: {exc}') from exc
                if result.returncode:
                    raise WorkspaceUnavailable(f'workspace for {repository}: {result.stderr.strip()}')
            else:
                _add(repository, path, branch, head)
            made.append((repository, path, branch, head, True, not existing))
    except WorkspaceUnavailable:
        for repository, path, branch, _, added, new_branch in reversed(made):
            if added:
                remove_registration(repository, path)
            if new_branch:
                _git('branch', '-D', branch, cwd=repository)
        raise
    for repository, path, branch, head, _, _ in made:
        if not workspace_for(spaces, repository):
            db._exec('INSERT INTO task_workspaces(conv_id,repository,path,branch,base_sha) '
                     'VALUES(?,?,?,?,?)', (conv_id, repository, path, branch, head))
    return True
