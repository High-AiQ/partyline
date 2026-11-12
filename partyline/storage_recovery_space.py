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
    available = shutil.disk_usage(common).free - RESERVE

    def check(required):
        if required > available:
            raise RecoverySpaceError('insufficient free space for recovery; source retained '
                                     f'(need {required + RESERVE} bytes including reserve)')

    check(0)
    if not registered:
        skipped = frozenset(os.path.join(path, name) for name in excluded)
        check(Budget(seconds=float('inf')).size(path, skipped))
        return
    # Stream names, never build preview evidence or retain a per-file listing.
    # Ignored caches need no recovery space. Existing tracked blobs make this
    # estimate conservative; it deliberately does not guess compression ratios.
    required = 0
    with subprocess.Popen(['git', 'ls-files', '--cached', '--others', '--exclude-standard',
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
