"""Content identity for cleanup without an interactive per-file evidence listing."""

import hashlib
import os
import subprocess
import tempfile


def add_paths(excluded):
    return ['.', *(':(top,literal,exclude)' + name.replace(os.sep, '/') for name in excluded)]


def stage_working(git, path, excluded=(), *, force=False):
    """Stage explicit file names, never ask Git to recurse into denied folders.

    Exclusion pathspecs naming ignored folders can themselves make git add fail.
    A NUL pathspec file also bounds argv and supports unusual file names.
    """
    if not excluded:
        git('add', *(['--force'] if force else []), '-A', '--', '.')
        return
    if force:
        from .storage_orphan import entries
        names = entries(path, excluded)
    else:
        excluded = tuple(name.replace(os.sep, '/') for name in excluded)
        names = git('ls-files', '--cached', '--others', '--exclude-standard', '-z').split('\0')
    with tempfile.TemporaryDirectory(prefix='partyline-add-') as folder:
        listing = os.path.join(folder, 'paths')
        with open(listing, 'wb') as stream:
            for name in filter(None, names):
                if not any(name == p or name.startswith(p + '/') for p in excluded):
                    stream.write(os.fsencode(name) + b'\0')
        if os.path.getsize(listing):
            git('--literal-pathspecs', 'add', *(['--force'] if force else []), '-A',
                '--pathspec-from-file=' + listing, '--pathspec-file-nul')


def working_tree(path, head, excluded=()):
    # A private index lets Git hash any number of changes without altering staging.
    with tempfile.TemporaryDirectory(prefix='partyline-storage-state-') as folder:
        env = {**os.environ, 'GIT_INDEX_FILE': os.path.join(folder, 'index')}

        def git(*args):
            done = subprocess.run(['git', *args], cwd=path, env=env, capture_output=True,
                                  text=True, timeout=30)
            if done.returncode:
                raise ValueError('cannot inspect cleanup working tree: ' + done.stderr.strip())
            return done.stdout.rstrip('\n')

        git('read-tree', head)
        stage_working(git, path, excluded)
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
