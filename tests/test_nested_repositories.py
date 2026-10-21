"""Partyline never deletes a directory holding a nested git repository (data-loss lesson)."""

import os
import subprocess
import tempfile
import unittest

from partyline import retirement_force, storage_routes, task_review_checkout, worktree_lifecycle
from partyline.db import Db
from partyline.features import overridden
from partyline.line_worktree import REVIEW_DIR, WORKTREES_DIR
from partyline.nested_repositories import keep_reason, nested_repositories
from partyline.retirement_auxiliary import inspect_auxiliary
from partyline.review_worktrees import ReviewError, remove_review_path
from partyline.scratch_worktrees import SCRATCH_DIR, remove_scratch_path


def setUpModule():
    global _fence
    _fence = overridden(write_fence=False)
    _fence.__enter__()


def tearDownModule():
    _fence.__exit__(None, None, None)


def git(cwd, *args):
    return subprocess.run(['git', '-c', 'user.name=T', '-c', 'user.email=t@example.com', *args],
                          cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class NestedRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = os.path.join(self.directory.name, 'project')
        os.makedirs(self.root)
        git(self.root, 'init', '-q', '-b', 'main')
        git(self.root, 'commit', '-q', '--allow-empty', '-m', 'root')
        self.db = Db(os.path.join(self.directory.name, 'test.db'))
        self.addCleanup(self.db.close)

    def worktree(self, folder, name='w'):
        path = os.path.join(self.root, folder, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        git(self.root, 'worktree', 'add', '-q', '--detach', path, 'HEAD')
        return path

    def clone_into(self, worktree, name='argon-backend'):
        """An ignored nested clone holding a commit that exists nowhere else."""
        clone = os.path.join(worktree, name)
        os.makedirs(clone)
        git(clone, 'init', '-q', '-b', 'main')
        git(clone, 'commit', '-q', '--allow-empty', '-m', 'unpushed work')
        with open(os.path.join(self.root, '.git', 'info', 'exclude'), 'a') as handle:
            handle.write(f'/{name}/\n')
        git(worktree, 'status', '--porcelain')
        self.tip = git(clone, 'rev-parse', 'HEAD')
        self.clone = clone
        return clone

    def intact(self):
        self.assertTrue(os.path.isdir(self.clone), 'the nested clone was deleted')
        self.assertEqual(git(self.clone, 'rev-parse', 'HEAD'), self.tip)

    def test_the_walk_finds_ignored_clones_and_skips_node_modules_and_its_own_git(self):
        tree = self.worktree(WORKTREES_DIR)
        self.assertEqual(nested_repositories(tree), [])
        self.clone_into(tree)
        os.makedirs(os.path.join(tree, 'node_modules', 'dep', '.git'))
        deep = os.path.join(tree, *'abcdefghij', 'deep')
        os.makedirs(os.path.join(deep, '.git'))
        self.assertEqual(nested_repositories(tree), ['argon-backend'])
        self.assertEqual(nested_repositories(tree, max_depth=20), ['a/b/c/d/e/f/g/h/i/j/deep',
                                                                    'argon-backend'])
        self.assertIsNone(keep_reason(os.path.join(tree, 'missing')))
        self.assertIn('contains repositories argon-backend', keep_reason(tree))

    def test_a_clean_looking_worktree_is_not_clean_and_is_not_removed(self):
        tree = self.worktree(WORKTREES_DIR)
        self.clone_into(tree)
        self.assertEqual(git(tree, 'status', '--porcelain'), '')  # git cannot see it
        self.assertFalse(worktree_lifecycle._is_clean(tree))
        self.db.create_conversation('line', 'Line')
        self.db._exec('UPDATE conversations SET cwd=? WHERE id=?', (tree, 'line'))
        conv = self.db.get_conversation('line')
        self.assertIn('contains repositories', worktree_lifecycle.worktree_removal_reason(self.db, conv))
        self.assertEqual(worktree_lifecycle.archive_worktree_if_safe(self.db, 'line')[0], False)
        worktree_lifecycle.remove_for_line(conv)
        self.assertFalse(worktree_lifecycle.discard_worktree(self.db, 'line'))
        worktree_lifecycle._sweep_repo(self.root, set())
        self.intact()

    def test_review_and_scratch_checkouts_keep_nested_clones(self):
        for folder, remove in ((REVIEW_DIR, remove_review_path), (SCRATCH_DIR, remove_scratch_path)):
            tree = self.worktree(folder, f'{folder}-sha')
            self.clone_into(tree, f'clone-{folder}'.replace('.', ''))
            self.assertFalse(remove(tree))
            self.intact()

    def test_force_retirement_and_storage_clear_keep_nested_clones(self):
        tree = self.worktree(WORKTREES_DIR)
        self.clone_into(tree)
        state = {'root': self.root, 'cwd': tree, 'branch_tip': None, 'branch': 'x'}
        self.assertFalse(retirement_force._remove(state))
        self.assertIsNone(storage_routes._remove(self.db, 'sessions', tree))
        review = self.worktree(REVIEW_DIR, 'r1')
        self.clone_into(review, 'other')
        self.assertIsNone(storage_routes._remove(self.db, 'review', review))
        self.assertTrue(os.path.isdir(self.clone))

    def test_an_auxiliary_checkout_holding_a_clone_counts_as_dirty(self):
        tree = self.worktree(REVIEW_DIR, 'r2')
        self.clone_into(tree)
        self.db.create_conversation('line', 'Line')
        self.db._exec('INSERT INTO review_worktrees(conv_id,sha,path,created_at) VALUES(?,?,?,0)',
                      ('line', git(tree, 'rev-parse', 'HEAD'), tree))
        preserved, pruned, _history = inspect_auxiliary(self.db, 'line')
        self.assertEqual(preserved['review_worktrees'], [tree])
        self.assertEqual(pruned['review_worktrees'], [])

    def test_task_review_checkout_keeps_clones_and_uses_a_single_force_clean(self):
        path = task_review_checkout.task_review_path(self.root, 'conv')
        os.makedirs(path)  # an unregistered directory under .review is replaced... unless it holds a repo
        self.clone_into(path)
        with self.assertRaises(ReviewError):
            task_review_checkout._move(self.db, 'conv', self.root, git(self.root, 'rev-parse', 'HEAD'))
        self.intact()
        os.rename(path, path + '.moved')
        full = git(self.root, 'rev-parse', 'HEAD')
        task_review_checkout._move(self.db, 'conv', self.root, full)
        clone = os.path.join(path, 'inner')
        os.makedirs(clone)
        git(clone, 'init', '-q')
        git(clone, 'commit', '-q', '--allow-empty', '-m', 'work')
        tip = git(clone, 'rev-parse', 'HEAD')
        task_review_checkout._move(self.db, 'conv', self.root, full)
        self.assertEqual(git(clone, 'rev-parse', 'HEAD'), tip)
