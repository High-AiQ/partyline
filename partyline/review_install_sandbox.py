"""Restrict package installers to the review checkout and existing package caches."""

from __future__ import annotations

import os
import signal
import subprocess
import sys

from .fence_darwin import quote
from .git_fence import _worktree_gitdir
from .review_scope import ReviewError


class DependencyError(ReviewError):
    """A review checkout cannot safely provision its dependencies."""

    def __init__(self, detail: str):
        super().__init__(409, f"review dependency provisioning failed: {detail}; "
                              "JavaScript lifecycle scripts are disabled for built-in installs")


def local_cache(checkout: str, name: str) -> str:
    """Keep temporary files in this worktree's private Git metadata, not its files."""
    root = os.path.realpath(checkout)
    gitdir = _worktree_gitdir(root)
    if not gitdir or os.path.islink(gitdir):
        raise DependencyError('review checkout has no private Git worktree directory')
    gitdir = os.path.realpath(gitdir)
    try:
        with open(os.path.join(gitdir, 'gitdir'), encoding='utf-8') as marker:
            registered = os.path.realpath(marker.read().strip())
        if registered != os.path.join(root, '.git'):
            raise DependencyError('review checkout Git directory does not belong to it')
        path = os.path.join(gitdir, 'partyline-package-cache', name)
        if os.path.realpath(path) != path:
            raise DependencyError('local package cache traverses a symlink')
        os.makedirs(path, exist_ok=True)
        return path
    except OSError as exc:
        raise DependencyError(f'cannot create review package cache: {exc}') from exc


def cache_location(checkout: str, name: str, relative: str) -> str:
    """Use the host cache if safe, otherwise a writable cache in the checkout."""
    home = os.path.realpath(os.path.expanduser('~'))
    path = os.path.join(home, relative)
    if (os.path.isdir(path) and os.path.realpath(path) == path
            and os.path.commonpath((path, os.path.realpath(checkout))) != path):
        return path
    return local_cache(checkout, name)


def install_argv(checkout: str, command: tuple[str, ...], local: str) -> list[str]:
    """Fail closed; installer configuration and plugins can execute arbitrary code."""
    checkout = os.path.realpath(checkout)
    home = os.path.realpath(os.path.expanduser('~'))
    candidates = [os.path.join(home, path) for path in (
        '.npm', '.cache/yarn', '.local/share/pnpm/store', '.yarn/berry/cache', '.cache/uv')]
    caches = [path for path in candidates if os.path.isdir(path)
              and os.path.realpath(path) == path
              and os.path.commonpath((path, checkout)) != path]
    caches.append(local)
    if sys.platform.startswith('linux'):
        tool = '/usr/bin/bwrap'
        if not os.access(tool, os.X_OK):
            raise DependencyError('bubblewrap is unavailable; cannot safely run the installer')
        argv = [tool, '--ro-bind', '/', '/', '--dev-bind', '/dev', '/dev', '--proc', '/proc',
                '--unshare-user', '--unshare-pid', '--bind', checkout, checkout]
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


def _kill_session(session: int) -> bool:
    """Kill each process still in the install session, including separate process groups."""
    try:
        os.killpg(session, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        listing = subprocess.run(['/bin/ps', '-A', '-o', 'pid='], stdin=subprocess.DEVNULL,
                                 capture_output=True, text=True, timeout=5,
                                 start_new_session=True, check=True)
    except (OSError, subprocess.SubprocessError):
        return False
    complete = True
    for token in listing.stdout.split():
        try:
            pid = int(token)
            if os.getsid(pid) == session:
                os.kill(pid, signal.SIGKILL)
        except (ValueError, ProcessLookupError):
            continue
        except PermissionError:
            complete = False
    return complete


def run_installer(argv: list[str], *, cwd: str, env: dict, timeout: int) -> subprocess.CompletedProcess:
    """Isolate the terminal and terminate the installer's entire process group on timeout."""
    process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        terminated = _kill_session(process.pid)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            terminated = False
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()
        if not terminated:
            raise DependencyError('installer timed out; could not terminate the entire session') from None
        raise
    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
