"""Ignored content is a person's decision unless it is a documented cache."""

import fnmatch
import os

from .line_worktree import _git
from .storage_survey import Budget

# Component patterns, at any depth. Keep this single list shared by automatic
# cleanup and legacy lifecycle reclamation. Never treat a generic "cache" folder
# as disposable: browser profiles and application data often use that name.
IGNORED_CACHE_PATTERNS = (
    '.venv', 'venv', 'virtualenv', 'env', '__pycache__', 'node_modules',
    '.pytest_cache', '.ruff_cache', '.mypy_cache', '.hypothesis', '.tox', '.nox',
    '.cache', '.next', '.nuxt', '.parcel-cache', '.turbo', '.svelte-kit',
    'build', 'dist', '*.egg-info',
)


def cache_path(name):
    return any(fnmatch.fnmatchcase(part, pattern) for part in name.replace('\\', '/').split('/')
               for pattern in IGNORED_CACHE_PATTERNS)


def ignored_paths(path, common=None):
    prefix = ('--git-dir', common, '--work-tree', path) if common else ()
    done = _git(*prefix, 'ls-files', '--others', '--ignored', '--exclude-standard', '--directory', '-z',
                cwd=common or path)
    if done.returncode:
        raise ValueError('cannot inspect ignored files; retained')
    return [name.rstrip('/') for name in filter(None, done.stdout.split('\0'))]


def ignored_reason(path, *, excluded=(), common=None):
    excluded = tuple(name.replace(os.sep, '/') for name in excluded)
    examples, count, size = [], 0, 0
    for name in ignored_paths(path, common):
        if cache_path(name) or any(name == p or name.startswith(p + '/') for p in excluded):
            continue
        # An ignored parent may contain a denied subtree; measure only the
        # readable portion and leave the denied subtree to partial removal.
        skipped = frozenset(os.path.join(path, p) for p in excluded)
        measured = Budget(seconds=float('inf')).size(os.path.join(path, name), skipped)
        if not measured and any(p.startswith(name + '/') for p in excluded):
            continue
        count += 1
        size += measured
        if len(examples) < 5:
            examples.append(f'{name[:240]} ({measured} bytes)')
    if count:
        return (f'ignored files outside known caches: {count} paths, {size} bytes; '
                + ', '.join(examples) + '; review or remove anyway')
    return None
