"""Discover directories and registrations, including missing and plain task folders."""

import logging
import os
import subprocess
from pathlib import Path

from .line_worktree import _git, repo_root, WORKTREES_DIR
from .task_workspaces import workspaces
from .worktree_paths import managed_root

logger = logging.getLogger(__name__)


def registrations(root):
    listing = _git('worktree', 'list', '--porcelain', '-z', cwd=root)
    if listing.returncode:
        return {}
    result, current = {}, None
    for field in listing.stdout.split('\0'):
        if field.startswith('worktree '):
            current = os.path.normpath(field.removeprefix('worktree '))
            result[current] = None
        elif current and field.startswith('HEAD '):
            result[current] = field.removeprefix('HEAD ')
    return result


def candidates(db, line=None):
    lines = db.list_conversations() + db.list_conversations(archived=True)
    if line:
        lines.append(line)
    roots, owners, found = set(), {}, {}
    cwds = {row['cwd'] for row in db._exec('SELECT cwd FROM attachments WHERE cwd IS NOT NULL').fetchall()}
    for conv in lines:
        cwd = conv.get('cwd')
        if cwd:
            cwds.add(cwd)
            owners[os.path.realpath(cwd)] = conv
        for item in workspaces(db, conv['id']):
            roots.add(item['repository'])
            owners[os.path.realpath(item['path'])] = conv
            found[os.path.normpath(item['path'])] = os.path.realpath(item['repository'])
    for cwd in cwds:
        if root := managed_root(cwd) or repo_root(cwd):
            roots.add(root)
    for root in sorted({os.path.realpath(root) for root in roots}):
        try:
            directory = Path(root) / WORKTREES_DIR
            if directory.is_dir() and not directory.is_symlink():
                for path in directory.iterdir():
                    if path.is_dir() and not path.is_symlink():
                        found.setdefault(str(path), root)
            for path in registrations(root):
                if managed_root(path) and not os.path.islink(path):
                    found[path] = root
        except (OSError, subprocess.SubprocessError):
            logger.exception('cannot enumerate worktrees in %s; continuing', root)
    result = []
    for path, root in sorted(found.items()):
        owner = owners.get(os.path.realpath(path))
        if owner is None:
            owner = next((conv for cwd, conv in owners.items() if managed_root(cwd)
                          and path.startswith(cwd + os.sep)), None)
        result.append((root, path, owner))
    return result
