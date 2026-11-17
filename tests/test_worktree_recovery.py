"""Real Git registrations, including the lock file left by an interrupted add."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from partyline.db import Db
from partyline.line_worktree import _git, place_child
from partyline.line_subtree import archive_line
from partyline.task_workspaces import WorkspaceUnavailable, place_task, workspaces
from partyline.worktree_lifecycle import archive_worktree_if_safe, sweep_orphaned_worktrees
from partyline.worktree_recovery import (
    add_worktree, heal_initializing, registrations, remove_registration,
)


class RecoveryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.make_repo('repo')
        self.db = Db(str(self.base / 'test.db'))
        self.addCleanup(self.db.close)
        self.db.create_conversation('root', 'Root')
        # Plain line, person-attached process, no captain and no conversation cwd.
        self.db.add_attachment('person-process', 'root', 'person-process', 'fake', ['fake'],
                               str(self.repo), 'owner')
        self.db.create_conversation('kid', 'kid')

    def git(self, repo, *args):
        result = _git('-c', 'user.name=Test', '-c', 'user.email=test@example.test', *args, cwd=str(repo))
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def make_repo(self, name):
        repo = self.base / name
        repo.mkdir(parents=True)
        self.git(repo, 'init', '-q', '-b', 'main')
        self.git(repo, 'commit', '--allow-empty', '-qm', 'initial')
        return repo

    def interrupted(self, repo, path, branch=None, reason='initializing', missing=True):
        args = ['worktree', 'add', '--no-checkout']
        args += ['-b', branch] if branch else ['--detach']
        self.git(repo, *args, str(path), 'HEAD')
        gitdir = self.git(path, 'rev-parse', '--absolute-git-dir')
        # Git writes this administrative file while initializing a checkout.
        Path(gitdir, 'locked').write_text(reason)
        if missing:
            shutil.rmtree(path)
        return str(path)

    def paths(self, repo):
        return {row['worktree'] for row in registrations(str(repo))}

    def test_git_prune_and_single_force_skip_initializing_locks(self):
        path = self.interrupted(self.repo, self.repo / '.partyline-worktrees' / 'orphan')
        self.git(self.repo, 'worktree', 'prune', '--expire=now')
        self.assertIn(path, self.paths(self.repo))
        self.assertNotEqual(_git('worktree', 'remove', '-f', path, cwd=str(self.repo)).returncode, 0)
        self.assertTrue(remove_registration(str(self.repo), path))
        self.assertNotIn(path, self.paths(self.repo))

    def test_failed_second_nested_add_rolls_back_both_repositories(self):
        folder = self.base / 'umbrella'
        folder.mkdir()
        repos = [self.make_repo('umbrella/a'), self.make_repo('umbrella/b')]
        self.db._exec("UPDATE attachments SET cwd=? WHERE id='person-process'", (str(folder),))

        def fail_second(*args, cwd):
            if args[:2] == ('worktree', 'add') and cwd == str(repos[1]):
                # Real Git created its ref/registration before the checkout was interrupted.
                done = _git(*args[:2], '--no-checkout', *args[2:], cwd=cwd)
                self.assertEqual(done.returncode, 0, done.stderr)
                path = args[4]
                gitdir = self.git(path, 'rev-parse', '--absolute-git-dir')
                Path(gitdir, 'locked').write_text('initializing')
                Path(path, 'partial').write_text('checkout in progress')
                return subprocess.CompletedProcess(args, 128, '', 'interrupted checkout')
            done = _git(*args, cwd=cwd)
            if args[:2] == ('worktree', 'add') and done.returncode == 0:
                gitdir = self.git(args[4], 'rev-parse', '--absolute-git-dir')
                Path(gitdir, 'locked').write_text('initializing')
            return done

        with patch('partyline.task_workspaces._git', side_effect=fail_second):
            with self.assertRaisesRegex(WorkspaceUnavailable, 'interrupted checkout'):
                place_task(self.db, 'root', 'kid')
        for repo in repos:
            self.assertEqual(self.paths(repo), {str(repo)})
            self.assertNotEqual(_git('show-ref', '--verify', 'refs/heads/line/kid',
                                     cwd=str(repo)).returncode, 0)
        self.assertFalse((folder / '.partyline-worktrees' / 'kid').exists())
        self.assertEqual(workspaces(self.db, 'kid'), [])

    def test_failed_add_preserves_existing_registration_branch_and_directory(self):
        path = self.interrupted(self.repo, self.repo / '.partyline-worktrees' / 'held',
                                'line/held', missing=False)
        done = add_worktree(str(self.repo), path, '-b', 'line/held', path, 'HEAD',
                            git=_git, branch='line/held')
        self.assertNotEqual(done.returncode, 0)
        self.assertIn(path, self.paths(self.repo))
        self.assertTrue(Path(path).is_dir())
        self.git(self.repo, 'show-ref', '--verify', 'refs/heads/line/held')

    def test_timeout_rolls_back_new_branch_and_partial_registration(self):
        path = str(self.repo / '.partyline-worktrees' / 'timeout')

        def timeout(*args, cwd):
            if args[:2] == ('worktree', 'add'):
                self.interrupted(self.repo, Path(path), 'line/timeout', missing=False)
                raise subprocess.TimeoutExpired('git', 30)
            return _git(*args, cwd=cwd)

        with self.assertRaises(subprocess.TimeoutExpired):
            add_worktree(str(self.repo), path, '-b', 'line/timeout', path, 'HEAD',
                         git=timeout, branch='line/timeout')
        self.assertNotIn(path, self.paths(self.repo))
        self.assertFalse(Path(path).exists())
        self.assertNotEqual(_git('show-ref', '--verify', 'refs/heads/line/timeout',
                                 cwd=str(self.repo)).returncode, 0)

    async def test_archiving_plain_line_clears_missing_nested_initializing_registration(self):
        placed = place_task(self.db, 'root', 'kid')
        nested = self.make_repo('repo/nested')
        path = self.interrupted(nested, Path(placed['cwd']) / 'nested', 'line/kid')
        self.db._exec('INSERT INTO task_workspaces(conv_id,repository,path,branch,base_sha) '
                      'VALUES(?,?,?,?,?)', ('kid', str(nested), path, 'line/kid',
                                            self.git(nested, 'rev-parse', 'HEAD')))
        runtime = SimpleNamespace(db=self.db, broadcast=AsyncMock(),
                                  stop_attachments=AsyncMock(return_value=[]), sockets={})
        with patch('partyline.line_subtree.close_for_line', new=AsyncMock()), \
             patch('partyline.line_subtree.docker_relay.stop', new=AsyncMock()):
            await archive_line(runtime, 'kid')
        self.assertNotIn(path, self.paths(nested))

    def test_retirement_removes_present_locked_worktree(self):
        placed = place_child(self.db, 'root', 'kid')
        gitdir = self.git(placed['cwd'], 'rev-parse', '--absolute-git-dir')
        Path(gitdir, 'locked').write_text('initializing')
        self.assertEqual(archive_worktree_if_safe(self.db, 'kid'), (True, None))
        self.assertNotIn(placed['cwd'], self.paths(self.repo))

    def test_startup_heals_archived_nested_and_orphan_but_keeps_other_locks(self):
        nested = self.make_repo('repo/nested')
        archived = self.interrupted(nested, self.repo / '.partyline-worktrees' / 'kid' / 'nested')
        self.db._exec("UPDATE conversations SET cwd=? WHERE id='kid'",
                      (str(self.repo / '.partyline-worktrees' / 'kid'),))
        self.db.archive_conversation('kid')
        orphan = self.interrupted(nested, self.repo / '.partyline-worktrees' / 'orphan' / 'nested')
        outside = self.interrupted(nested, self.base / 'unrelated')
        deliberate = self.interrupted(nested, self.repo / '.partyline-worktrees' / 'kept',
                                      reason='on removable drive')
        present = self.interrupted(nested, self.repo / '.partyline-worktrees' / 'present', missing=False)
        manual = self.interrupted(self.repo, self.repo / '.partyline-worktrees' / 'manual',
                                  reason='user lock', missing=False)
        active = self.interrupted(nested, self.repo / '.partyline-worktrees' / 'live' / 'nested')
        self.db.create_conversation('live', 'Live')
        self.db.add_attachment('live-process', 'live', 'live-process', 'fake', ['fake'],
                               str(self.repo / '.partyline-worktrees' / 'live'), 'owner')
        with self.assertLogs('partyline.worktree_recovery', level='INFO') as logs:
            sweep_orphaned_worktrees(self.db)
        self.assertTrue(any(archived in entry for entry in logs.output))
        self.assertTrue(any(orphan in entry for entry in logs.output))
        paths = self.paths(nested)
        self.assertNotIn(archived, paths)
        self.assertNotIn(orphan, paths)
        self.assertTrue({outside, deliberate, present, active} <= paths)
        self.assertIn(manual, self.paths(self.repo))
        self.assertTrue(Path(manual).is_dir())

    def test_auxiliary_missing_registrations_keep_live_owners_and_custom_names(self):
        sha = self.git(self.repo, 'rev-parse', 'HEAD')
        for directory, table in (('.review', 'review_worktrees'), ('.scratch', 'scratch_worktrees')):
            path = self.interrupted(self.repo, self.repo / directory / sha)
            custom = self.interrupted(self.repo, self.repo / directory / 'personal')
            self.db._exec(f'INSERT INTO {table}(conv_id,sha,path,created_at) VALUES(?,?,?,?)',
                          ('kid', sha, path, 1))
            sweep_orphaned_worktrees(self.db)
            self.assertIn(path, self.paths(self.repo))
            self.assertIsNotNone(self.db._exec(f'SELECT 1 FROM {table} WHERE path=?', (path,)).fetchone())
            self.db.archive_conversation('kid')
            heal_initializing(self.db)
            self.assertNotIn(path, self.paths(self.repo))
            self.assertIn(custom, self.paths(self.repo))
            self.db._exec("UPDATE conversations SET archived_at=NULL WHERE id='kid'")

    def test_failed_detached_and_child_adds_leave_no_registration_or_partial_tree(self):
        from partyline.review_scope import ReviewError
        from partyline.review_worktrees import create_review_worktree
        from partyline.scratch_worktrees import create_scratch_worktree
        from partyline.task_review_checkout import _move

        self.db._exec("UPDATE conversations SET cwd=? WHERE id='kid'", (str(self.repo),))
        sha = self.git(self.repo, 'rev-parse', 'HEAD')
        calls = [
            ('partyline.review_worktrees', lambda: create_review_worktree(self.db, 'kid', sha)),
            ('partyline.scratch_worktrees', lambda: create_scratch_worktree(self.db, 'kid', sha)),
            ('partyline.task_review_checkout', lambda: _move(self.db, 'kid', str(self.repo), sha)),
        ]

        def fail_checkout(*args, cwd):
            if args[:2] != ('worktree', 'add'):
                return _git(*args, cwd=cwd)
            done = _git(*args[:2], '--no-checkout', *args[2:], cwd=cwd)
            self.assertEqual(done.returncode, 0, done.stderr)
            path = args[3] if args[2] == '--detach' else args[4]
            Path(self.git(path, 'rev-parse', '--absolute-git-dir'), 'locked').write_text('initializing')
            Path(path, 'partial').write_text('partial')
            return subprocess.CompletedProcess(args, 128, '', 'interrupted checkout')

        for module, create in calls:
            with self.subTest(module=module), patch(module + '._git', side_effect=fail_checkout):
                with self.assertRaises(ReviewError):
                    create()
                self.assertEqual(self.paths(self.repo), {str(self.repo)})
                self.assertEqual(list(self.repo.rglob('partial')), [])
        with patch('partyline.line_worktree._git', side_effect=fail_checkout):
            placed = place_child(self.db, 'root', 'kid', base='HEAD')
        self.assertIsNone(placed['branch'])
        self.assertEqual(self.paths(self.repo), {str(self.repo)})
        self.assertNotEqual(_git('show-ref', '--verify', 'refs/heads/line/kid',
                                 cwd=str(self.repo)).returncode, 0)

    def test_failed_add_restores_preexisting_empty_directory(self):
        path = self.repo / '.partyline-worktrees' / 'empty'
        path.mkdir(parents=True)

        def fail_checkout(*args, cwd):
            if args[:2] != ('worktree', 'add'):
                return _git(*args, cwd=cwd)
            self.interrupted(self.repo, path, missing=False)
            return subprocess.CompletedProcess(args, 128, '', 'interrupted checkout')

        done = add_worktree(str(self.repo), str(path), '--detach', str(path), 'HEAD', git=fail_checkout)
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(self.paths(self.repo), {str(self.repo)})
        self.assertEqual(list(path.iterdir()), [])

    def test_archive_recovery_spares_an_add_before_its_line_record_is_written(self):
        path = str(self.repo / '.partyline-worktrees' / 'in-progress')

        def adding(*args, cwd):
            if args[:2] != ('worktree', 'add'):
                return _git(*args, cwd=cwd)
            self.interrupted(self.repo, Path(path))
            heal_initializing(self.db)
            self.assertIn(path, self.paths(self.repo))
            return subprocess.CompletedProcess(args, 0, '', '')

        add_worktree(str(self.repo), path, '--detach', path, 'HEAD', git=adding)
        heal_initializing(self.db)
        self.assertNotIn(path, self.paths(self.repo))
