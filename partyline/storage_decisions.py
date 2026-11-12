"""Cheap invalidation for kept trees using only the decision's own inputs.

Manual cleanup always retries. Automatic starts stat recorded tree directories
and HEAD/index, and read the tree's own ref value (loose or packed). Unrelated
merges, fetches and ref packing do not invalidate the decision. Content-only
edits without directory or Git changes require a manual retry.
"""

import json
import os

from .git_fence import _read_ref


def stamp(path):
    try:
        info = os.lstat(path)
        return [info.st_dev, info.st_ino, info.st_mode, info.st_size,
                info.st_mtime_ns, info.st_ctime_ns]
    except OSError:
        return None


def evidence(path):
    paths, refs = {path}, []

    def git_inputs(gitdir, common=None):
        common = common or gitdir
        if os.path.basename(os.path.dirname(gitdir)) == 'worktrees':
            common = os.path.dirname(os.path.dirname(gitdir))
        paths.update(os.path.join(gitdir, name) for name in ('HEAD', 'index', 'commondir'))
        paths.update(os.path.join(common, name) for name in ('info/exclude', 'config'))
        try:
            with open(os.path.join(gitdir, 'HEAD'), encoding='utf-8') as stream:
                head = stream.read(8192).strip()
            if head.startswith('ref: '):
                ref = head.removeprefix('ref: ')
                refs.append([common, ref, _read_ref(common, ref)])
        except (OSError, UnicodeError):
            pass

    for directory, dirs, files in os.walk(path):
        paths.add(directory)
        paths.update(os.path.join(directory, name) for name in ('.gitignore', '.gitattributes'))
        link = os.path.join(directory, '.git')
        if '.git' in dirs:
            git_inputs(link)
        dirs[:] = [name for name in dirs if name != '.git']
        if '.git' in files:
            paths.add(link)
            try:
                with open(link, encoding='utf-8') as stream:
                    target = stream.read(8192).strip().removeprefix('gitdir:').strip()
                git_inputs(os.path.realpath(os.path.join(directory, target)))
            except (OSError, UnicodeError):
                pass
    if os.path.isdir(os.path.join(path, 'refs')):  # private mirror, not the owner's refs
        git_inputs(path)
    return json.dumps({'paths': {name: stamp(name) for name in sorted(paths)}, 'refs': refs})


def remember(db, path):
    db._exec('INSERT INTO storage_cleanup_decisions(path,evidence) VALUES(?,?) '
             'ON CONFLICT(path) DO UPDATE SET evidence=excluded.evidence',
             (str(path), evidence(str(path))))


def unchanged(db, path):
    row = db._exec('SELECT evidence FROM storage_cleanup_decisions WHERE path=?',
                   (str(path),)).fetchone()
    if not row:
        return False
    previous = json.loads(row['evidence'])
    # Old evidence watched all owner refs. Reclassify it once into narrow inputs.
    if 'paths' not in previous:
        return False
    return (all(stamp(name) == value for name, value in previous['paths'].items()) and
            all(_read_ref(common, ref) == value for common, ref, value in previous['refs']))
