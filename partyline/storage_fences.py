"""Reclaim purged lines' private refs only after anchoring every tip in its owner."""

import hashlib
import os
from pathlib import Path
import subprocess
import uuid

from . import git_fence
from .line_worktree import _git, rev
from .storage_cleanup import attachment_reason, attempt, remove_path
from .storage_survey import known_repositories, planned_ids


def owners(db, line=None):
    roots = set(known_repositories(db))
    roots.update(row['repository'] for row in db._exec('SELECT repository FROM task_workspaces').fetchall())
    if line and line.get('cwd'):
        from .worktree_paths import managed_root
        if root := managed_root(line['cwd']):
            roots.add(root)
    result = {}
    for root in roots:
        common = rev(root, 'rev-parse', '--path-format=absolute', '--git-common-dir')
        if common:
            key = hashlib.sha256(common.encode()).hexdigest()[:16]
            result['git-' + key] = (root, common)
    return result


def preserve(mirror, root, common):
    if mirror.is_symlink():
        return 'symbolic mirror retained'
    env = {**os.environ, 'GIT_OBJECT_DIRECTORY': os.path.join(common, 'objects')}
    if (mirror / 'objects').is_dir():
        env['GIT_ALTERNATE_OBJECT_DIRECTORIES'] = str(mirror / 'objects')

    def refs():
        done = subprocess.run(['git', '--git-dir', str(mirror), 'for-each-ref',
                               '--format=%(objectname) %(refname)'], env=env,
                              capture_output=True, text=True, timeout=30)
        if done.returncode:
            raise ValueError('cannot inspect mirror refs')
        return done.stdout.splitlines()

    before = refs()
    durable = _git('for-each-ref', '--format=%(objectname)', cwd=root)
    if durable.returncode:
        raise ValueError('cannot inspect repository refs')
    anchored = set(durable.stdout.splitlines())
    for entry in before:
        tip, ref = entry.split(' ', 1)
        if tip in anchored:
            continue
        if _git('cat-file', '-e', tip, cwd=root).returncode:
            # Fetch imports mirror-only objects as well as the ref, without moving a branch.
            recovery = 'refs/partyline/discarded/storage-' + uuid.uuid4().hex + '/mirror'
            done = subprocess.run(['git', 'fetch', '--no-write-fetch-head', str(mirror),
                                   f'{ref}:{recovery}'], cwd=root,
                                  env={**os.environ, 'GIT_ALTERNATE_OBJECT_DIRECTORIES':
                                       os.path.join(common, 'objects')},
                                  capture_output=True, text=True, timeout=30)
            if done.returncode:
                raise ValueError('cannot recover mirror-only objects')
        else:
            recovery = 'refs/partyline/discarded/storage-' + uuid.uuid4().hex + '/mirror'
            if _git('update-ref', recovery, tip, cwd=root).returncode:
                raise ValueError('cannot anchor mirror ref')
        if (rev(root, 'rev-parse', '--verify', recovery) != tip or
                _git('cat-file', '-e', tip, cwd=root).returncode):
            raise ValueError('mirror recovery verification failed')
    if refs() != before:
        raise ValueError('mirror refs changed during recovery; retained')
    return None


def clean_fences(db, report, line=None):
    base = Path(git_fence.FENCE_ROOT)
    if not base.is_dir() or base.is_symlink():
        return
    repositories = owners(db, line)
    for folder in sorted(base.iterdir()):
        if not folder.is_dir() or folder.is_symlink():
            continue
        if line and folder.name != line['id']:
            continue
        # Current mirrors are keyed by line; also protect legacy attachment-keyed homes.
        attachment = db.get_attachment(folder.name)
        owner_id = attachment['conv_id'] if attachment else folder.name
        if db.get_conversation(owner_id) and not (line and owner_id == line['id']):
            continue
        for mirror in sorted(folder.iterdir()):
            def clean(mirror=mirror, folder=folder):
                if reason := attachment_reason(db, folder.name):
                    return reason
                if db.get_conversation(folder.name) and not line:
                    return 'line still exists'
                ids = {att['id'] for att in db.list_attachments(folder.name)}
                if ids & planned_ids(db) or any(attachment_reason(db, ident) for ident in ids):
                    return 'line has a live or restart-planned attachment'
                if mirror.name not in repositories:
                    return 'owning repository is unavailable; mirror refs retained'
                root, common = repositories[mirror.name]
                preserve(mirror, root, common)
                if reason := attachment_reason(db, folder.name):
                    return reason
                if any(attachment_reason(db, ident) for ident in ids):
                    return 'line has a live or restart-planned attachment'
                remove_path(mirror)
                return None
            attempt(report, mirror, clean)
        try:
            folder.rmdir()
        except OSError:
            pass  # Kept mirrors or an unknown file remain.
