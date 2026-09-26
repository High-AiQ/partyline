"""Portable managed-worktree paths and names with isolated Windows ref directories."""

import ntpath
import posixpath
import sys


def branch_name(cwd, platform=None):
    windows = (sys.platform if platform is None else platform) == 'win32'
    path = ntpath if windows else posixpath
    name = path.basename(path.normpath(cwd))
    # Atomic Git ref updates create a sibling .lock file. A private directory
    # permits those writes without granting writes to another line's refs.
    return f'line/{name}/work' if windows else f'line/{name}'


def managed_root(cwd, platform=None):
    windows = (sys.platform if platform is None else platform) == 'win32'
    normalized = ntpath.normpath(cwd).replace('\\', '/') if windows else posixpath.normpath(cwd)
    marker = '/.partyline-worktrees/'
    return normalized.split(marker, 1)[0] if marker in normalized else None
