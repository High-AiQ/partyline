"""Write raw orphan blobs in bulk without invoking Git clean filters."""

import os
import subprocess
import tempfile


def quoted_path(path):
    # hash-object --stdin-paths accepts Git's C-quoted pathname format. It has
    # no NUL mode; escape controls, quotes and backslashes without losing bytes.
    escaped = []
    for byte in os.fsencode(path):
        if byte in (34, 92):
            escaped.append(b'\\' + bytes([byte]))
        elif byte < 32 or byte == 127:
            escaped.append(f'\\{byte:03o}'.encode())
        else:
            escaped.append(bytes([byte]))
    return b'"' + b''.join(escaped) + b'"\n'


def write_blobs(common, path, listing, env):
    def run(*args, **kwargs):
        done = subprocess.run(['git', 'hash-object', '-w', '--no-filters', *args],
                              cwd=common, env=env, stdout=subprocess.DEVNULL,
                              stderr=subprocess.PIPE, timeout=30, **kwargs)
        if done.returncode:
            raise ValueError('cannot write raw orphan recovery blobs; retained')

    with tempfile.TemporaryFile() as paths, open(listing, 'rb') as names:
        for name in filter(None, names.read().split(b'\0')):
            full = os.path.join(path, os.fsdecode(name))
            if os.path.islink(full):
                run('--stdin', input=os.fsencode(os.readlink(full)))
            else:
                paths.write(quoted_path(full))
        if paths.tell():
            paths.seek(0)
            run('--stdin-paths', stdin=paths)
