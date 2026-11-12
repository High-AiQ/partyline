"""Reclaim purged lines' private refs only after anchoring every tip in its owner."""

import errno
import hashlib
import subprocess
import uuid

from .line_worktree import _git, repo_root, rev
from .worktree_paths import managed_root
from .storage_cleanup import attempt, kept, remove_path
from . import storage_kept, storage_decisions
from .storage_mirror import MirrorUnreadable, repository_view
from .storage_recovery_space import require_space
from .storage_fence_inventory import folders, mirrors, retention, summarize


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
        raise MirrorUnreadable('cannot inspect mirror refs: ' + done.stderr.strip())
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
            require_space(common, mirror / 'objects', registered=False)
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


def clean_fences(db, report, line=None, *, retry_failed=False, recovery=None):
    repositories = None
    for folder in folders(db, line):
        reason = retention(db, folder, line)
        entries = mirrors(folder, lambda path, error: kept(report, path, error))
        if reason:
            summarize(report['retained_mirrors'], db, folder, reason, len(entries))
            continue
        for mirror in entries:
            if not retry_failed and (failure := storage_kept.reason(db, mirror)) and (
                    storage_kept.reason(db, mirror, suppressed_only=True) or
                    storage_decisions.unchanged(db, mirror)):
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
                if recovery:
                    recovery.watch(common)
                suppress = False
                try:
                    reason = preserve(mirror, root, common)
                except (OSError, ValueError, subprocess.SubprocessError) as exc:
                    reason = str(exc)
                    suppress = isinstance(exc, MirrorUnreadable) or (
                        isinstance(exc, OSError) and exc.errno in (errno.EACCES, errno.EPERM))
                if reason:
                    storage_kept.remember(db, mirror, reason, suppress_retry=suppress)
                    return reason
                with db._runtime_serialized():
                    if reason := retention(db, folder, line):
                        return reason
                    remove_path(mirror)
                    storage_kept.forget(db, mirror)
                    return None
            attempt(report, mirror, clean)
            if mirror.is_dir() and storage_kept.reason(db, mirror):
                owner = repositories.get(mirror.name) if repositories else None
                storage_decisions.remember(db, mirror, owner[1] if owner else mirror.parent)
        try:
            folder.rmdir()
        except OSError:
            pass  # Kept mirrors or an unknown file remain.
