"""Targeted recovery of failed adds and Git's abandoned initializing locks."""

import logging
import os
import re
import shutil
import subprocess
import threading

logger = logging.getLogger(__name__)
_ADDING = {}
_ADDING_LOCK = threading.RLock()
_AUX_NAME = re.compile(r'(?:[0-9a-f]{40}(?:-onto-[0-9a-f]{40})?|task-[\w-]+)')


def registrations(root):
    from .line_worktree import _git
    done = _git('worktree', 'list', '--porcelain', '-z', cwd=root)
    if done.returncode:
        raise OSError('cannot inspect worktree registrations')
    rows = []
    for record in done.stdout.split('\0\0'):
        row = dict(field.partition(' ')[::2] for field in record.split('\0') if field)
        if 'worktree' in row:
            row['worktree'] = os.path.normpath(row['worktree'])
            rows.append(row)
    return rows


def locked_paths(root):
    """Startup directory sweeps must preserve locks the recovery pass left alone."""
    return {row['worktree'] for row in registrations(root) if 'locked' in row}


def owned_path(path):
    """Canonical managed checkout paths only, including nested task repositories."""
    if not os.path.isabs(path) or os.path.realpath(path) != path:
        return False
    return any(f'/{name}/' in path.replace(os.sep, '/')
               for name in ('.partyline-worktrees', '.review', '.scratch'))


def remove_registration(root, path):
    """Double force only the caller's managed path, never a repository-wide prune."""
    from .line_worktree import _git
    if not owned_path(path):
        return False
    try:
        return _git('worktree', 'remove', '-f', '-f', path, cwd=root).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def add_worktree(root, path, *args, git, branch=None):
    """Run one add; on failure undo only state absent before this attempt."""
    with _ADDING_LOCK:
        _ADDING[path] = _ADDING.get(path, 0) + 1
    try:
        return _add_worktree(root, path, *args, git=git, branch=branch)
    finally:
        with _ADDING_LOCK:
            _ADDING[path] -= 1
            if not _ADDING[path]:
                del _ADDING[path]


def _add_worktree(root, path, *args, git, branch):
    before = {row['worktree'] for row in registrations(root)}
    existed = os.path.lexists(path)
    had_branch = branch and git('show-ref', '--verify', '--quiet',
                                f'refs/heads/{branch}', cwd=root).returncode == 0

    def rollback():
        created_registration = path not in before and any(
            row['worktree'] == path for row in registrations(root))
        if path not in before and (not existed or created_registration) and owned_path(path):
            remove_registration(root, path)
            if os.path.isdir(path):
                shutil.rmtree(path)
            elif os.path.lexists(path):
                os.unlink(path)
            if existed:
                os.makedirs(path, exist_ok=True)
        if branch and not had_branch:
            git('branch', '-D', branch, cwd=root)

    try:
        done = git('worktree', 'add', *args, cwd=root)
    except (OSError, subprocess.SubprocessError):
        rollback()
        raise
    if done.returncode:
        rollback()
    return done


def _owns(cwd, path):
    return bool(cwd and (path == cwd or (owned_path(cwd)
                         and path.startswith(cwd.rstrip(os.sep) + os.sep))))


def _owners(db, path, conversations):
    owners = set()
    for table in ('task_workspaces', 'review_worktrees', 'scratch_worktrees'):
        owners.update(row['conv_id'] for row in db._exec(
            f'SELECT conv_id FROM {table} WHERE path=?', (path,)).fetchall())
    for conv in conversations:
        cwd = conv.get('cwd')
        if _owns(cwd, path):
            owners.add(conv['id'])
        # Root/plain lines may have their only cwd on a person-attached process.
        for att in db.list_attachments(conv['id']):
            if _owns(att.get('cwd'), path):
                owners.add(conv['id'])
    for marker in ('/.review/task-', '/.scratch/task-'):
        if marker in path.replace(os.sep, '/'):
            owners.add(path.replace(os.sep, '/').split(marker, 1)[1].split('/', 1)[0])
    return owners


def heal_repository(db, root, conversations):
    """Remove only missing, initializing, managed registrations without a live owner."""
    try:
        rows = registrations(root)
        for row in rows:
            path = row['worktree']
            if row.get('locked') != 'initializing' or os.path.lexists(path) or not owned_path(path):
                continue
            # Without a database record, only recognized auxiliary names are ours.
            if '/.partyline-worktrees/' not in path.replace(os.sep, '/'):
                if not _AUX_NAME.fullmatch(os.path.basename(path)):
                    continue
            owners = _owners(db, path, conversations)
            if any((conv := db.get_conversation(ident)) and not conv.get('archived_at')
                   for ident in owners):
                continue
            with _ADDING_LOCK:
                if path in _ADDING or os.path.lexists(path):
                    continue  # a concurrent add has not recorded its line ownership yet
                if remove_registration(root, path):
                    logger.info('worktree recovery: removed initializing registration %s in %s', path, root)
    except (OSError, subprocess.SubprocessError):
        logger.exception('worktree recovery failed in %s', root)


def heal_initializing(db):
    """Discover repositories from lines, attachments and durable workspace records."""
    from .line_worktree import repo_root
    from .task_workspaces import repositories_under
    from .worktree_paths import managed_root

    conversations = db.list_conversations(archived=False) + db.list_conversations(archived=True)
    paths = {conv['cwd'] for conv in conversations if conv.get('cwd')}
    paths.update(row['cwd'] for row in db._exec(
        "SELECT DISTINCT cwd FROM attachments WHERE cwd IS NOT NULL AND cwd != ''").fetchall())
    roots = {row['repository'] for row in db._exec('SELECT repository FROM task_workspaces').fetchall()}
    for base in {managed_root(path) or path for path in paths}:
        if os.path.isdir(base):
            roots.update(repositories_under(base))
        if root := repo_root(base):
            roots.add(root)
    for table, marker in (('review_worktrees', '/.review/'), ('scratch_worktrees', '/.scratch/')):
        roots.update(os.path.normpath(row['path'].replace(os.sep, '/').split(marker, 1)[0])
                     for row in db._exec(f'SELECT path FROM {table}').fetchall()
                     if marker in row['path'].replace(os.sep, '/'))
    for root in sorted(roots):
        if os.path.isdir(root):
            heal_repository(db, root, conversations)
