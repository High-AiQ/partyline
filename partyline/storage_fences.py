"""Reclaim purged lines' private refs only after anchoring every tip in its owner."""

import hashlib
import subprocess
import uuid

from .line_worktree import _git, repo_root, rev
from .worktree_paths import managed_root
from .storage_cleanup import attempt, kept, remove_path
from . import storage_kept
from .storage_mirror import repository_view
from .storage_fence_inventory import folders, mirrors, retention


def owners(db, line=None):
    if line:
        from .task_workspaces import workspaces
        roots = {item['repository'] for item in workspaces(db, line['id'])}
        if root := managed_root(line.get('cwd') or ''):
            roots.add(root)
        for att in db.list_attachments(line['id']):
            if root := repo_root(att.get('cwd')):
                roots.add(root)
    else:
        # Metadata is enough to coalesce thousands of attachments before Git.
        cwds = {row['cwd'] for row in db._exec(
            'SELECT cwd FROM conversations UNION SELECT cwd FROM attachments').fetchall() if row['cwd']}
        cwds = {managed_root(cwd) or cwd for cwd in cwds}
        roots = {root for cwd in cwds if (root := repo_root(cwd))}
        roots.update(row['repository'] for row in
                     db._exec('SELECT repository FROM task_workspaces').fetchall())
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
    with repository_view(mirror, common) as view:
        return preserve_view(mirror, view, root, common)


def mirror_refs(view):
    done = subprocess.run(['git', '--git-dir', str(view), 'for-each-ref',
                           '--format=%(objectname) %(refname)'],
                          capture_output=True, text=True, timeout=30)
    if done.returncode or done.stderr.strip():
        raise ValueError('cannot inspect mirror refs: ' + done.stderr.strip())
    return done.stdout.splitlines()


def preserve_view(mirror, view, root, common):
    before = mirror_refs(view)
    durable = _git('for-each-ref', '--format=%(objectname)', cwd=root)
    if durable.returncode:
        raise ValueError('cannot inspect repository refs')
    anchored = set(durable.stdout.splitlines())
    for entry in before:
        tip, ref = entry.split(' ', 1)
        if tip in anchored:
            continue
        recovery = 'refs/partyline/discarded/storage-' + uuid.uuid4().hex + '/mirror'
        if _git('cat-file', '-e', tip, cwd=root).returncode:
            done = subprocess.run(['git', 'fetch', '--no-write-fetch-head', str(view),
                                   f'{ref}:{recovery}'], cwd=root,
                                  capture_output=True, text=True, timeout=30)
            if done.returncode:
                raise ValueError('cannot recover mirror-only objects: ' + done.stderr.strip())
        elif _git('update-ref', recovery, tip, cwd=root).returncode:
            raise ValueError('cannot anchor mirror ref')
        if (rev(root, 'rev-parse', '--verify', recovery) != tip or
                _git('cat-file', '-e', tip, cwd=root).returncode):
            raise ValueError('mirror recovery verification failed')
    with repository_view(mirror, common) as current:
        if mirror_refs(current) != before:
            raise ValueError('mirror refs changed during recovery; retained')
    return None


def clean_fences(db, report, line=None, *, retry_failed=False):
    repositories = None
    for folder in folders(db, line):
        reason = retention(db, folder, line)
        for mirror in mirrors(folder, lambda path, error: kept(report, path, error)):
            if reason:
                kept(report, mirror, reason)
                continue
            if not retry_failed and (failure := storage_kept.reason(db, mirror)):
                kept(report, mirror, failure)
                continue
            if repositories is None:
                repositories = owners(db, line)

            def clean(mirror=mirror, folder=folder, repositories=repositories):
                if reason := retention(db, folder, line):
                    return reason
                if mirror.name not in repositories:
                    reason = 'owning repository is unavailable; mirror refs retained'
                    storage_kept.remember(db, mirror, reason)
                    return reason
                root, common = repositories[mirror.name]
                try:
                    reason = preserve(mirror, root, common)
                except (OSError, ValueError, subprocess.SubprocessError) as exc:
                    reason = str(exc)
                if reason:
                    storage_kept.remember(db, mirror, reason)
                    return reason
                with db._runtime_serialized():
                    if reason := retention(db, folder, line):
                        return reason
                    remove_path(mirror)
                    storage_kept.forget(db, mirror)
                    return None
            attempt(report, mirror, clean)
        try:
            folder.rmdir()
        except OSError:
            pass  # Kept mirrors or an unknown file remain.
