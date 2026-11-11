"""Restrict package installers to the review checkout and existing package caches."""

from __future__ import annotations

import os
import sys

from .fence_darwin import quote
from .review_scope import ReviewError


class DependencyError(ReviewError):
    """A review checkout cannot safely provision its dependencies."""

    def __init__(self, detail: str):
        super().__init__(409, f"review dependency provisioning failed: {detail}; "
                              "lifecycle scripts are disabled")


def local_cache(checkout: str, name: str) -> str:
    """Do not follow repository-controlled symlinks when creating server directories."""
    root = os.path.realpath(checkout)
    path = os.path.join(root, '.partyline-package-cache', name)
    if os.path.realpath(path) != path:
        raise DependencyError('local package cache traverses a symlink')
    os.makedirs(path, exist_ok=True)
    return path


def cache_location(checkout: str, name: str, relative: str) -> str:
    """Use the host cache if safe, otherwise a writable cache in the checkout."""
    home = os.path.realpath(os.path.expanduser('~'))
    path = os.path.join(home, relative)
    if (os.path.isdir(path) and os.path.realpath(path) == path
            and os.path.commonpath((path, os.path.realpath(checkout))) != path):
        return path
    return local_cache(checkout, name)


def install_argv(checkout: str, command: tuple[str, ...]) -> list[str]:
    """Fail closed; installer configuration and plugins can execute arbitrary code."""
    checkout = os.path.realpath(checkout)
    home = os.path.realpath(os.path.expanduser('~'))
    candidates = [os.path.join(home, path) for path in (
        '.npm', '.cache/yarn', '.local/share/pnpm/store', '.yarn/berry/cache')]
    caches = [path for path in candidates if os.path.isdir(path)
              and os.path.realpath(path) == path
              and os.path.commonpath((path, checkout)) != path]
    if sys.platform.startswith('linux'):
        tool = '/usr/bin/bwrap'
        if not os.access(tool, os.X_OK):
            raise DependencyError('bubblewrap is unavailable; cannot safely run the installer')
        argv = [tool, '--ro-bind', '/', '/', '--dev-bind', '/dev', '/dev', '--proc', '/proc',
                '--unshare-user', '--bind', checkout, checkout]
        for cache in caches:
            argv += ['--bind', cache, cache]
        return [*argv, '--die-with-parent', '--', *command]
    if sys.platform == 'darwin':
        tool = '/usr/bin/sandbox-exec'
        if not os.access(tool, os.X_OK):
            raise DependencyError('sandbox-exec is unavailable; cannot safely run the installer')
        paths = [checkout, *caches]
        allow = ' '.join(f'(subpath {quote(path)})' for path in paths)
        profile = (f'(version 1)(allow default)(deny file-write*)'
                   f'(allow file-write* {allow} (literal "/dev/null"))')
        return [tool, '-p', profile, *command]
    raise DependencyError('no installer sandbox is available on this platform')
