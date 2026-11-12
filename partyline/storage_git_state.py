"""Content identity for cleanup without an interactive per-file evidence listing."""

import hashlib
import os
import subprocess
import tempfile


def add_paths(excluded):
    return ['.', *(':(top,literal,exclude)' + name.replace(os.sep, '/') for name in excluded)]


def working_tree(path, head, excluded=()):
    # A private index lets Git hash any number of changes without altering staging.
    with tempfile.TemporaryDirectory(prefix='partyline-storage-state-') as folder:
        env = {**os.environ, 'GIT_INDEX_FILE': os.path.join(folder, 'index')}

        def git(*args):
            done = subprocess.run(['git', *args], cwd=path, env=env, capture_output=True,
                                  text=True, timeout=30)
            if done.returncode:
                raise ValueError('cannot inspect cleanup working tree: ' + done.stderr.strip())
            return done.stdout.strip()

        git('read-tree', head)
        git('add', '-A', '--', *add_paths(excluded))
        return git('write-tree')


def index_identity(path):
    digest = hashlib.sha256()
    try:
        with open(path, 'rb') as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except FileNotFoundError:
        return None
    return digest.hexdigest()
