"""Conservative free-space checks before Git creates recovery objects."""

import os
import shutil
import stat
import subprocess

from .storage_git_state import add_paths
from .storage_survey import Budget

RESERVE = 16 * 1024 * 1024


class RecoverySpaceError(ValueError):
    pass


def require_space(common, path, *, registered=True, excluded=()):
    available = None

    def check(required):
        nonlocal available
        if not required:
            return
        if available is None:
            available = shutil.disk_usage(common).free - RESERVE
        if required > available:
            raise RecoverySpaceError('insufficient free space for recovery; source retained '
                                     f'(need {required + RESERVE} bytes including reserve)')

    if not registered:
        skipped = frozenset(os.path.join(path, name) for name in excluded)
        check(Budget(seconds=float('inf')).size(path, skipped))
        return
    # Stream names, never build preview evidence or retain a per-file listing.
    # Only modified/untracked content may require new blobs. Committed and
    # staged blobs already reside in Git; ignored caches need no recovery space.
    # A zero-content estimate also needs no reserve or disk-space check.
    required = 0
    with subprocess.Popen(['git', 'ls-files', '--modified', '--others', '--exclude-standard',
                           '-z', '--', *add_paths(excluded)], cwd=path,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
        try:
            pending = b''
            while chunk := process.stdout.read(65536):
                pending += chunk
                while b'\0' in pending:
                    name, pending = pending.split(b'\0', 1)
                    try:
                        info = os.lstat(os.path.join(path, os.fsdecode(name)))
                    except FileNotFoundError:
                        continue
                    if stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                        required += info.st_size
                        check(required)
            if process.wait(timeout=30):
                raise ValueError('cannot estimate recovery space; source retained')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
