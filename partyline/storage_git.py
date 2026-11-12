"""Reuse forced-retirement recovery refs before automatic worktree removal."""

import os
import subprocess
import uuid

from .git_fence import mirror_branch_ref
from .line_worktree import _git, rev
from .retirement_git import file_evidence, snapshot, tracked_modes
from .retirement_worktree import refuse_orphan


def state(root, path, conv_id=None):
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
    names = set(filter(None, git('diff', '--name-only', '-z', 'HEAD').split('\0')))
    names.update(filter(None, git('diff', '--cached', '--name-only', '-z').split('\0')))
    names.update(filter(None, git('ls-files', '--others', '--exclude-standard', '-z').split('\0')))
    files, _ = file_evidence(path, names, tracked=tracked_modes(path), conv_id=conv_id)
    index = git('rev-parse', '--path-format=absolute', '--git-path', 'index')
    index_files, _ = file_evidence(os.path.dirname(index), [os.path.basename(index)])
    return {'root': root, 'cwd': path, 'head': head,
            'branch_tip': rev(root, 'rev-parse', branch) if branch else None,
            'mirror_tip': mirror, 'index_path': index, 'files': files, 'index': index_files}


def merged_tips(root, tips):
    from .worktree_lifecycle import _default_branch

    base = _default_branch(root)
    tips = list(dict.fromkeys(tip for tip in tips if tip))
    if not base or not tips:
        return False
    done = _git('rev-list', *tips, '--not', base, cwd=root)
    return done.returncode == 0 and not done.stdout.strip()


def recover(root, path, conv_id=None, *, merged=None):
    before = state(root, path, conv_id)
    clean_merged = merged if merged is not None else merged_tips(
        root, [before['head'], before['branch_tip'], before['mirror_tip']])
    if not before['files'] and clean_merged:
        return before
    refs = snapshot(before, 'storage-' + uuid.uuid4().hex)
    if before != state(root, path, conv_id):
        raise ValueError('worktree changed while saving recovery refs; retained')
    # Recovery must reside in the real repository, never solely in a private mirror.
    for ref, tip in refs.items():
        if _git('rev-parse', '--verify', ref, cwd=root).stdout.strip() != tip:
            raise ValueError('recovery ref verification failed; retained')
    return before


def recover_plain(root, path):
    """An unregistered orphan folder has no index: preserve all files as a new tree."""
    from .worktree_storage import repositories

    if repositories(path, check_files=True) or os.path.lexists(os.path.join(path, '.git')):
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
        git('add', '--force', '-A', '--', '.')
        tree = git('write-tree')
        if not git('ls-files', '-z'):
            return
        tip = git('commit-tree', tree, '-m', 'Partyline orphan recovery')
        git('update-ref', 'refs/partyline/discarded/storage-' + uuid.uuid4().hex + '/snapshot', tip)
        git('add', '--force', '-A', '--', '.')
        if git('write-tree') != tree:
            raise ValueError('orphan folder changed during recovery; retained')
