"""The server can remove an empty orphan after checking its surviving branch."""

import os

from .line_worktree import rev, _git
from .storage_orphan import dangling_owner
from .worktree_paths import branch_name


def empty_merged(root, path, branch=None, conv_id=None):
    if not root or not os.path.isdir(path) or os.path.realpath(path) != path:
        return False
    owner = dangling_owner(path)
    link = os.path.join(path, '.git')
    if os.path.lexists(link) and (not owner or os.path.islink(link)):
        return False
    common = rev(root, 'rev-parse', '--path-format=absolute', '--git-common-dir')
    if owner and (not common or os.path.normcase(owner) != os.path.normcase(os.path.realpath(common))):
        return False

    def fail(error):
        raise error

    try:
        for directory, dirs, files in os.walk(path, onerror=fail):
            if any(name != '.git' or directory != path for name in files):
                return False
            if any(os.path.islink(os.path.join(directory, name)) for name in dirs):
                return False
    except OSError:
        return False
    name = branch or branch_name(path)
    tip = rev(root, 'rev-parse', '--verify', 'refs/heads/' + name)
    from .storage_git import merged_tips
    from .git_fence import _read_ref, mirror_store
    mirror = mirror_store(root, conv_id) if conv_id else None
    private = _read_ref(mirror, 'refs/heads/' + name) if mirror else None
    return bool(tip and merged_tips(root, [tip, private]))


def remove_empty(root, path, branch=None, conv_id=None):
    if not empty_merged(root, path, branch, conv_id):
        return False
    from .storage_cleanup import remove_path
    remove_path(path)
    _git('worktree', 'remove', '--force', path, cwd=root)
    return True


def empty_task(db, conv):
    """An empty plain task container may hold pruned workspaces in other repos."""
    from .task_workspaces import workspaces
    cwd = conv.get('cwd') or ''
    if not cwd or os.path.realpath(cwd) != cwd or os.path.lexists(os.path.join(cwd, '.git')):
        return False
    spaces = workspaces(db, conv.get('id') or '')
    if not spaces or not all(empty_merged(item['repository'], item['path'], item['branch'], conv['id'])
                             for item in spaces):
        return False
    links = {os.path.join(item['path'], '.git') for item in spaces}

    def fail(error):
        raise error

    try:
        for directory, dirs, files in os.walk(cwd, onerror=fail):
            if any(os.path.join(directory, name) not in links for name in files):
                return False
            if any(os.path.islink(os.path.join(directory, name)) for name in dirs):
                return False
    except OSError:
        return False
    return True


def remove_task(db, conv):
    if not empty_task(db, conv):
        return False
    from .task_workspaces import workspaces
    from .storage_cleanup import remove_path
    for item in workspaces(db, conv['id']):
        if not remove_empty(item['repository'], item['path'], item['branch'], conv['id']):
            return False
    cwd = conv['cwd']

    def fail(error):
        raise error

    # Recheck the container after removing the registered empty workspaces.
    for directory, dirs, files in os.walk(cwd, onerror=fail):
        if files or any(os.path.islink(os.path.join(directory, name)) for name in dirs):
            return False
    remove_path(cwd)
    return True
