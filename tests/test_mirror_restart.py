"""Resuming a line must preserve commits that its captain has not accepted."""

import os
from pathlib import Path
import unittest
from unittest.mock import patch

from partyline import fence_paths, git_fence
from tests import test_fence
from tests.test_fence import _git, _identity


class MirrorRestartTest(unittest.TestCase):
    setUp = test_fence.GitMirrorTest.setUp
    mirror_root = test_fence.GitMirrorTest.mirror_root
    gitdir = test_fence.GitMirrorTest.gitdir

    def test_resume_with_review_keeps_unaccepted_tip_and_reflog(self):
        repo, cwd = self.fix['repo'], self.fix['line_wt']
        accepted = _git('rev-parse', 'HEAD', cwd=cwd).stdout.strip()
        # Create a genuine later commit, then leave only the mirror pointing at it.
        _identity('commit', '-q', '--allow-empty', '-m', 'unaccepted', cwd=cwd)
        tip = _git('rev-parse', 'HEAD', cwd=cwd).stdout.strip()
        review = os.path.join(repo, '.review', tip)
        _git('worktree', 'add', '--detach', review, tip, cwd=repo)
        att = {'cwd': cwd, 'conv_id': 'restart-line', 'review_worktrees': [
            {'path': review, 'sha': tip, 'conv_id': 'restart-line'}]}
        common = git_fence.common_gitdir(self.gitdir(cwd))
        with patch.object(git_fence, 'FENCE_ROOT', self.mirror_root()):
            mirror = git_fence.refresh_mirror(common, self.gitdir(cwd), 'restart-line')
            ref = Path(mirror, 'refs/heads/line/demo')
            log = Path(mirror, 'logs/refs/heads/line/demo')
            before_log = log.read_bytes()
            _git('update-ref', 'refs/heads/line/demo', accepted, cwd=repo)
            for _ in range(2):
                binds = fence_paths.write_set(att)
                self.assertEqual(ref.read_text().strip(), tip)
                self.assertEqual(log.read_bytes(), before_log)
                review_gitdir = self.gitdir(review)
                self.assertIn((review_gitdir, review_gitdir, False), binds)
                self.assertEqual(sum(dst == common for _, dst, _ in binds), 1)
            self.assertEqual(_git('rev-parse', 'line/demo', cwd=repo).stdout.strip(), accepted)

    def test_resume_without_review_keeps_own_reflog(self):
        cwd = self.fix['line_wt']
        common = git_fence.common_gitdir(self.gitdir(cwd))
        with patch.object(git_fence, 'FENCE_ROOT', self.mirror_root()):
            mirror = git_fence.refresh_mirror(common, self.gitdir(cwd), 'restart-line')
            log = Path(mirror, 'logs/refs/heads/line/demo')
            preserved = log.read_bytes() + b'private unaccepted reflog entry\n'
            log.write_bytes(preserved)
            fence_paths.write_set({'cwd': cwd, 'conv_id': 'restart-line'})
            self.assertEqual(log.read_bytes(), preserved)


if __name__ == '__main__':
    unittest.main()
