"""Content recovery for linked checkouts whose per-worktree metadata was pruned."""

import hashlib
import os
import stat
import subprocess
import tempfile
import uuid

from .line_worktree import rev
from .storage_recovery_space import require_space
from .storage_raw_blobs import write_blobs
from .storage_git_objects import reachable, normalized


def dangling_owner(path):
    """A .git link is a hint only; validate its surviving common object store."""
    link = os.path.join(path, '.git')
    try:
        if os.path.islink(link):
            return None
        with open(link, encoding='utf-8') as stream:
            text = stream.read(8192).strip()
        if not text.startswith('gitdir:'):
            return None
        metadata = os.path.realpath(os.path.join(path, text[7:].strip()))
        parent = os.path.dirname(metadata)
        if os.path.basename(parent) != 'worktrees' or os.path.exists(metadata):
            return None
        common = os.path.dirname(parent)
        resolved = rev(common, 'rev-parse', '--absolute-git-dir')
        if not resolved or os.path.normcase(os.path.realpath(resolved)) != os.path.normcase(common):
            return None
        return common
    except (OSError, UnicodeError):
        return None


def entries(path, excluded):
    def fail(error):
        raise error

    for directory, dirs, files in os.walk(path, followlinks=False, onerror=fail):
        relative = os.path.relpath(directory, path)
        dirs[:] = [name for name in dirs if name != '.git' and
                   os.path.normpath(os.path.join(relative, name)) not in excluded]
        for name in files + [name for name in dirs if os.path.islink(os.path.join(directory, name))]:
            name = os.path.normpath(os.path.join(relative, name))
            if name != '.git' and name not in excluded:
                yield name


def blob(path, algorithm):
    info = os.lstat(path)
    digest = hashlib.new(algorithm)
    if stat.S_ISLNK(info.st_mode):
        content = os.fsencode(os.readlink(path))
        digest.update(f'blob {len(content)}\0'.encode())
        digest.update(content)
        mode = '120000'
    elif stat.S_ISREG(info.st_mode):
        digest.update(f'blob {info.st_size}\0'.encode())
        with open(path, 'rb') as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        mode = '100755' if info.st_mode & stat.S_IXUSR else '100644'
    else:
        raise ValueError('orphan contains a special file; retained')
    after = os.lstat(path)
    fields = ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    if any(getattr(after, field) != getattr(info, field) for field in fields):
        raise ValueError('orphan changed while hashing; retained')
    return digest.hexdigest(), mode


def identity(path, excluded, algorithm):
    digest = hashlib.sha256()
    for name in sorted(entries(path, excluded)):
        oid, mode = blob(os.path.join(path, name), algorithm)
        digest.update(os.fsencode(name) + b'\0' + (mode + oid).encode())
    return digest.hexdigest()


def recover_dangling(common, path, *, excluded=(), reachable_objects=None):
    """Save content not reachable from surviving owner refs, by content hash.

    Never copy the checkout to the outer repo. Existing blobs may have different
    names or occur only in history; no index/HEAD remains to compare paths with.
    """
    algorithm = rev(common, 'rev-parse', '--show-object-format')
    if algorithm not in ('sha1', 'sha256'):
        raise ValueError('cannot determine orphan object format; retained')
    before = identity(path, excluded, algorithm)
    durable = reachable(common) if reachable_objects is None else reachable_objects
    files = [(name, *blob(os.path.join(path, name), algorithm)) for name in entries(path, excluded)]
    filtered = normalized(common, path, [name for name, oid, mode in files
                                        if oid not in durable and mode != '120000'])
    with tempfile.TemporaryDirectory(prefix='partyline-dangling-') as folder:
        env = {**os.environ, 'GIT_DIR': common, 'GIT_WORK_TREE': path,
               'GIT_INDEX_FILE': os.path.join(folder, 'index'),
               'GIT_AUTHOR_NAME': 'Partyline', 'GIT_AUTHOR_EMAIL': 'partyline@local',
               'GIT_COMMITTER_NAME': 'Partyline', 'GIT_COMMITTER_EMAIL': 'partyline@local'}

        def git(*args, stdin=None):
            done = subprocess.run(['git', *args], cwd=common, env=env,
                                  capture_output=True, text=True, timeout=30, stdin=stdin)
            if done.returncode:
                raise ValueError('cannot recover dangling worktree; retained: ' + done.stderr[:500])
            return done.stdout.rstrip('\n')

        listing = os.path.join(folder, 'paths')
        index_info = os.path.join(folder, 'index-info')
        unique_bytes = 0
        with open(listing, 'wb') as names, open(index_info, 'wb') as index, subprocess.Popen(
            ['git', '--git-dir', common, 'cat-file', '--batch-check=%(objecttype)'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        ) as process:
            try:
                for name, oid, mode in files:
                    if oid in durable or filtered.get(name) in durable:
                        continue
                    process.stdin.write((oid + '\n').encode())
                    process.stdin.flush()
                    answer = process.stdout.readline()
                    if answer not in (b'blob\n', (oid + ' missing\n').encode()):
                        raise ValueError('cannot inspect orphan object store; retained')
                    if answer != b'blob\n':
                        unique_bytes += os.lstat(os.path.join(path, name)).st_size
                        names.write(os.fsencode(name) + b'\0')
                    index.write((mode + ' ' + oid + '\t').encode() + os.fsencode(name) + b'\0')
                process.stdin.close()
                if process.wait(timeout=30):
                    raise ValueError('cannot inspect orphan object store; retained')
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        if os.path.getsize(index_info):
            # Present but unreachable blobs need a ref, not another copy.
            # Only missing raw blobs need space; committed gigabytes need neither.
            require_space(common, path, required_bytes=unique_bytes)
            git('read-tree', '--empty')
            write_blobs(common, path, listing, env)
            with open(index_info, 'rb') as index:
                git('update-index', '-z', '--index-info', stdin=index)
            tree = git('write-tree')
            tip = git('commit-tree', tree, '-m', 'Partyline dangling worktree recovery')
            git('update-ref', 'refs/partyline/discarded/storage-' + uuid.uuid4().hex + '/snapshot', tip)
        if identity(path, excluded, algorithm) != before:
            raise ValueError('orphan changed during recovery; retained')
    return before, algorithm


def remove_dangling(path, *, excluded=()):
    """Keep the ownership hint until every inspected entry has been removed."""
    from .storage_removal import remove_contents
    remove_contents(path, excluded=excluded, keep_git=True)
    os.unlink(os.path.join(path, '.git'))
    os.rmdir(path)
