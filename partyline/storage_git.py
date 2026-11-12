"""Reuse forced-retirement recovery refs before automatic worktree removal."""

import os
import subprocess
import uuid

from .git_fence import mirror_branch_ref
from .line_worktree import _git, rev
from .retirement_git import snapshot
from .storage_git_state import add_paths, index_identity, working_tree
from .retirement_worktree import refuse_orphan


def state(root, path, conv_id=None, *, excluded=()):
    refuse_orphan(root, path)

    def git(*args):
        done = _git(*args, cwd=path)
        if done.returncode:
            raise ValueError('cannot inspect Git state')
        return done.stdout.strip() if '-z' not in args else done.stdout

    head = git('rev-parse', 'HEAD')
    branch = rev(path, 'symbolic-ref', '-q', 'HEAD')
    mirror = (mirror_branch_ref(path, conv_id, branch.removeprefix('refs/heads/'))
              if branch and conv_id else None)
    tree = working_tree(path, mirror or head, excluded)
    staged = _git('diff', '--cached', '--quiet', 'HEAD', '--', cwd=path)
    if staged.returncode not in (0, 1):
        raise ValueError('cannot inspect cleanup index')
    index = git('rev-parse', '--path-format=absolute', '--git-path', 'index')
    return {'root': root, 'cwd': path, 'head': head,
            'branch_tip': rev(root, 'rev-parse', branch) if branch else None,
            'mirror_tip': mirror, 'index_path': index,
            'files': tree != git('rev-parse', 'HEAD^{tree}') or bool(staged.returncode),
            'excluded': tuple(excluded),
            'tree': tree, 'index': index_identity(index)}


def merged_tips(root, tips):
    from .worktree_lifecycle import _default_branch

    base = _default_branch(root)
    tips = list(dict.fromkeys(tip for tip in tips if tip))
    if not base or not tips:
        return False
    done = _git('rev-list', *tips, '--not', base, cwd=root)
    return done.returncode == 0 and not done.stdout.strip()


def recover(root, path, conv_id=None, *, merged=None, excluded=()):
    before = state(root, path, conv_id, excluded=excluded)
    clean_merged = merged if merged is not None else merged_tips(
        root, [before['head'], before['branch_tip'], before['mirror_tip']])
    if not before['files'] and clean_merged:
        return before
    refs = snapshot(before, 'storage-' + uuid.uuid4().hex)
    if before != state(root, path, conv_id, excluded=excluded):
        raise ValueError('worktree changed while saving recovery refs; retained')
    # Recovery must reside in the real repository, never solely in a private mirror.
    for ref, tip in refs.items():
        if _git('rev-parse', '--verify', ref, cwd=root).stdout.strip() != tip:
            raise ValueError('recovery ref verification failed; retained')
    return before


def recover_plain(root, path, *, excluded=()):
    """An unregistered orphan folder has no index: preserve all files as a new tree."""
    from .worktree_storage import repositories

    errors = []
    nested = repositories(path, check_files=True, errors=errors)
    if any(os.path.relpath(error.filename, path) not in excluded for error in errors):
        raise ValueError('orphan folder became unreadable; retained')
    if nested or os.path.lexists(os.path.join(path, '.git')):
        raise ValueError('unregistered repository; cannot prove recovery')
    import tempfile

    with tempfile.TemporaryDirectory(prefix='partyline-orphan-') as directory:
        common = rev(root, 'rev-parse', '--path-format=absolute', '--git-common-dir')
        if not common:
            raise ValueError('no repository for orphan recovery')
        env = {**os.environ, 'GIT_DIR': common, 'GIT_WORK_TREE': path,
               'GIT_INDEX_FILE': os.path.join(directory, 'index'),
               'GIT_AUTHOR_NAME': 'Partyline', 'GIT_AUTHOR_EMAIL': 'partyline@local',
               'GIT_COMMITTER_NAME': 'Partyline', 'GIT_COMMITTER_EMAIL': 'partyline@local'}

        def git(*args):
            done = subprocess.run(['git', *args], cwd=path, env=env, capture_output=True,
                                  text=True, timeout=30)
            if done.returncode:
                raise ValueError('cannot snapshot orphan folder')
            return done.stdout.strip()

        git('read-tree', '--empty')
        git('add', '--force', '-A', '--', *add_paths(excluded))
        tree = git('write-tree')
        if not git('ls-files', '-z'):
            return
        tip = git('commit-tree', tree, '-m', 'Partyline orphan recovery')
        git('update-ref', 'refs/partyline/discarded/storage-' + uuid.uuid4().hex + '/snapshot', tip)
        git('add', '--force', '-A', '--', *add_paths(excluded))
        if git('write-tree') != tree:
            raise ValueError('orphan folder changed during recovery; retained')
