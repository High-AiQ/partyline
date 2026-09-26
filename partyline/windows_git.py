"""Git carve-outs that allow only this Windows line's ref directory."""

from pathlib import Path

from . import git_fence
from .fence_paths import _review_directory, _review_worktree_paths
from .worktree_paths import branch_name, managed_root
from .line_worktree import _git


def write_paths(att):
    cwd = att.get('cwd') or ''
    result = [Path(cwd).resolve()]
    gitdir = git_fence._worktree_gitdir(cwd)
    if gitdir:
        expected = 'refs/heads/' + branch_name(cwd)
        actual = git_fence._head_branch(gitdir)
        if not managed_root(cwd) or actual != expected:
            raise OSError('Windows linked checkouts must use the branch assigned by Partyline')
        common = Path(git_fence.common_gitdir(gitdir)).resolve()
        root = managed_root(cwd)
        actual_common = _git('rev-parse', '--path-format=absolute', '--git-common-dir', cwd=root)
        registration = Path(gitdir) / 'gitdir'
        common_file = Path(gitdir) / 'commondir'
        if (actual_common.returncode or common != Path(actual_common.stdout.strip()).resolve()
                or Path(gitdir).resolve().parent != common / 'worktrees'
                or not common_file.is_file()
                or (Path(gitdir) / common_file.read_text().strip()).resolve() != common
                or not registration.is_file()
                or Path(registration.read_text().strip()).resolve() != Path(cwd, '.git').resolve()):
            raise OSError('Windows Git metadata does not belong to the managed worktree')
        result.extend([Path(gitdir).resolve(), common / 'objects',
                       common / Path(expected).parent, common / 'logs' / Path(expected).parent])
    review = _review_directory(cwd, create=True)
    if review:
        result.append(Path(review))
        for checkout in _review_worktree_paths(att, review):
            result.append(Path(git_fence._worktree_gitdir(checkout)))
    return [str(path) for path in result if path.is_dir()]
