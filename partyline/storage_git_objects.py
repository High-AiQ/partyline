"""Durable object reachability and non-writing normalized content comparison."""

import os
import subprocess
import tempfile

from .storage_raw_blobs import quoted_path


def reachable(common):
    objects = set()
    with subprocess.Popen(['git', '--git-dir', common, 'rev-list', '--objects', '--all',
                           '--no-object-names'], stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL) as process:
        try:
            for line in process.stdout:
                objects.add(line.strip().decode('ascii'))
            if process.wait(timeout=30):
                raise ValueError('cannot inspect reachable orphan objects; retained')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    return objects


def normalized(common, path, names):
    """Hash regular files through their checkout attributes, without Git -w.

    A reachable normalized blob also represents a committed CRLF or LFS
    checkout. Unmatched bytes are still saved raw, without clean filters.
    """
    if not names:
        return {}
    with tempfile.TemporaryFile() as paths, tempfile.TemporaryFile() as output:
        for name in names:
            paths.write(quoted_path(os.path.join(path, name)))
        paths.seek(0)
        env = {**os.environ, 'GIT_DIR': common, 'GIT_WORK_TREE': path}
        done = subprocess.run(['git', 'hash-object', '--stdin-paths'], cwd=path,
                              env=env, stdin=paths, stdout=output, stderr=subprocess.PIPE, timeout=30)
        if done.returncode:
            raise ValueError('cannot compare normalized orphan content; retained')
        output.seek(0)
        hashes = output.read().decode('ascii').splitlines()
    if len(hashes) != len(names) or any(len(oid) not in (40, 64) for oid in hashes):
        raise ValueError('incomplete normalized orphan comparison; retained')
    return dict(zip(names, hashes, strict=True))
