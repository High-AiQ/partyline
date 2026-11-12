"""Revisit retired and orphaned worktrees, preserving changes before removal."""

import logging
import os

from .line_worktree import _git
from .retirement_nested import linked_owner, surviving_owner
from .retirement_worktree import remove_directory
from .storage_cleanup import attachment_reason, attempt
from .storage_git import merged_tips, recover, recover_plain, state
from .storage_survey import inside
from .task_workspaces import workspaces
from .worktree_paths import managed_root
from .storage_worktree_inventory import candidates, registrations
from .worktree_storage import record_kept, repositories

logger = logging.getLogger(__name__)


def protected(db, path, owner=None, purging=False):
    # An open line may have adopted an orphan since enumeration.
    for conv in db.list_conversations():
        paths = [conv.get('cwd'), *(item['path'] for item in workspaces(db, conv['id']))]
        if any(cwd and (inside(cwd, path) or (managed_root(cwd) and inside(path, cwd)))
               for cwd in paths):
            if not (purging and owner and conv['id'] == owner['id']):
                return 'belongs to an open line'
    return in_use(db, path, owner)


def in_use(db, path, owner=None):
    if owner:
        for att in db.list_attachments(owner['id']):
            if reason := attachment_reason(db, att['id']):
                return reason
    for row in db._exec('SELECT id,cwd FROM attachments').fetchall():
        if row['cwd'] and inside(row['cwd'], path):
            if reason := attachment_reason(db, row['id']):
                return reason
    return None


def remove_worktree(db, root, path, owner=None, purging=False):
    """Recheck ownership and Git evidence at deletion, including nested worktrees."""
    if reason := protected(db, path, owner, purging):
        return reason
    if os.path.realpath(path) != path or os.path.islink(path):
        return 'worktree paths must be canonical'
    if not os.path.isdir(path):
        import uuid
        tip = registrations(root).get(path)
        if not tip:
            return None
        if not merged_tips(root, [tip]):
            ref = 'refs/partyline/discarded/storage-' + uuid.uuid4().hex + '/head'
            if _git('update-ref', ref, tip, cwd=root).returncode:
                return 'cannot preserve missing checkout HEAD'
        with db._runtime_serialized():
            if reason := protected(db, path, owner, purging):
                return reason
            if registrations(root).get(path) != tip:
                return 'missing checkout registration changed; retained'
            done = _git('worktree', 'remove', '--force', path, cwd=root)
            if done.returncode:
                return 'cannot remove missing checkout registration'
        return None
    if common := linked_owner(path):
        if not inside(common, path):
            root = common
    errors = []
    nested = repositories(path, check_files=True, errors=errors)
    excluded = tuple(os.path.relpath(error.filename, path) for error in errors)
    if any(name == '.' or name.startswith('..' + os.sep) for name in excluded):
        return 'cannot inspect worktree; retained'
    options = {'excluded': excluded} if excluded else {}
    # Preflight the whole folder before removing any nested checkout.
    for name in nested:
        full = os.path.join(path, name)
        common = surviving_owner(full, path)
        if not common:
            return f'contains independent nested repository {name}; its commits may exist nowhere else'
        if reason := protected(db, full):
            return reason
    for name in nested:
        full = os.path.join(path, name)
        common = linked_owner(full)
        reason = remove_worktree(db, common, full, owner, purging)
        if reason:
            return f'{full}: {reason}'
    if not os.path.isdir(path):
        return None
    if os.path.lexists(os.path.join(path, '.git')):
        before = recover(root, path, owner['id'] if owner else None, **options)
        with db._runtime_serialized():
            if reason := protected(db, path, owner, purging):
                return reason
            if before != state(root, path, owner['id'] if owner else None, **options):
                return 'worktree changed after recovery; retained'
            remove_directory(path, root, **options)
        _git('worktree', 'remove', '--force', path, cwd=root)
    else:
        # Plain task folders and unregistered leftovers get a tree in a surviving clone.
        repo = root
        if owner and (spaces := workspaces(db, owner['id'])):
            repo = spaces[0]['repository']
        recover_plain(repo, path, **options)
        with db._runtime_serialized():
            if reason := protected(db, path, owner, purging):
                return reason
            from .storage_cleanup import remove_path
            remove_path(path, **options)

    return None


def clean_worktrees(db, report, line=None, *, purging=False):
    for root, path, owner in candidates(db, line):
        if line and (not owner or owner['id'] != line['id']):
            continue
        if owner and not owner.get('archived_at') and line is None:
            continue
        attempt(report, path, lambda root=root, path=path, owner=owner:
                remove_worktree(db, root, path, owner, purging))
        if os.path.isdir(path):
            reason = next((item['reason'] for item in reversed(report['skipped']) if item['path'] == path),
                          'cleanup incomplete')
            try:
                record_kept(db, root, path, reason)
            except OSError:
                logger.exception("cannot record kept worktree %s; continuing", path)
