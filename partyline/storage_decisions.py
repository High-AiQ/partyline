"""Cheap invalidation for kept trees: directory mtimes and Git control files.

A manual cleanup always retries. Automatic starts stat the recorded evidence,
without walking or invoking Git. Changes within an existing file that leave its
parent directory and Git state unchanged require a manual retry.
"""

import json
import os


def stamp(path):
    try:
        info = os.lstat(path)
        return [info.st_dev, info.st_ino, info.st_mode, info.st_size,
                info.st_mtime_ns, info.st_ctime_ns]
    except OSError:
        return None


def evidence(path, root):
    paths = {path}
    stores = {os.path.join(root, '.git')}
    if os.path.isdir(os.path.join(root, 'objects')):
        stores = {root}
    for directory, dirs, files in os.walk(path):
        paths.add(directory)
        paths.update(os.path.join(directory, name) for name in ('.gitignore', '.gitattributes'))
        dirs[:] = [name for name in dirs if name != '.git']
        if '.git' in files:
            link = os.path.join(directory, '.git')
            paths.add(link)
            try:
                with open(link, encoding='utf-8') as stream:
                    target = stream.read(8192).strip().removeprefix('gitdir:').strip()
                gitdir = os.path.realpath(os.path.join(directory, target))
                paths.update(os.path.join(gitdir, name) for name in ('HEAD', 'index', 'commondir'))
                if os.path.basename(os.path.dirname(gitdir)) == 'worktrees':
                    stores.add(os.path.dirname(os.path.dirname(gitdir)))
            except (OSError, UnicodeError):
                pass
    # Ref changes elsewhere can resolve merge/ownership decisions. Include
    # loose and packed refs, without consulting Git on subsequent starts.
    for gitdir in stores:
        controls = ('HEAD', 'packed-refs', 'refs/heads', 'refs/remotes', 'info/exclude', 'config')
        paths.update(os.path.join(gitdir, name) for name in controls)
        for kind in ('heads', 'remotes'):
            for directory, _dirs, files in os.walk(os.path.join(gitdir, 'refs', kind)):
                paths.add(directory)
                paths.update(os.path.join(directory, name) for name in files)
    return json.dumps({name: stamp(name) for name in sorted(paths)})


def remember(db, path, root):
    db._exec('INSERT INTO storage_cleanup_decisions(path,evidence) VALUES(?,?) '
             'ON CONFLICT(path) DO UPDATE SET evidence=excluded.evidence',
             (str(path), evidence(str(path), str(root))))


def unchanged(db, path):
    row = db._exec('SELECT evidence FROM storage_cleanup_decisions WHERE path=?',
                   (str(path),)).fetchone()
    return bool(row and all(stamp(name) == value for name, value in json.loads(row['evidence']).items()))
