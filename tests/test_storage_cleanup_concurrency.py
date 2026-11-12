"""Ownership locks protect deletion without covering walks, recovery or startup."""

import asyncio
import os
import shutil
from unittest.mock import AsyncMock, patch

from partyline import runtime_lock, server, storage_cleanup as gc, storage_git
from partyline.retirement_worktree import remove_directory
from partyline.storage_fences import owners, preserve
from partyline.worktree_cleanup import cleanup as cleanup_worktree
from tests.storage_cleanup_fixture import CleanupFixture
from tests.orchestrator_fixture import git


class CleanupConcurrencyTest(CleanupFixture):
    def assert_runtime_lock_free(self):
        descriptor = os.open(self.db.runtime_lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            runtime_lock.try_lock(descriptor)
            runtime_lock.unlock(descriptor)
        finally:
            os.close(descriptor)

    def assert_runtime_lock_held(self):
        descriptor = os.open(self.db.runtime_lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            with self.assertRaises(BlockingIOError):
                runtime_lock.try_lock(descriptor)
        finally:
            os.close(descriptor)

    def test_walks_and_snapshots_release_runtime_lock_but_deletions_hold_it(self):
        path = self.child('dirty-lock')
        (path / 'only-copy').write_text('preserve this')
        self.att('stopped', session=None)
        size = gc.survey.Budget.size
        snapshot = storage_git.snapshot
        observed = []

        def measure(budget, *args):
            self.assert_runtime_lock_free()
            observed.append('size')
            return size(budget, *args)

        def recover(*args):
            self.assert_runtime_lock_free()
            observed.append('snapshot')
            return snapshot(*args)

        def remove(where, root):
            self.assert_runtime_lock_held()
            observed.append('delete')
            return remove_directory(where, root)

        def remove_file(where):
            self.assert_runtime_lock_held()
            return original_remove(where)

        original_remove = gc.remove_path
        with patch.object(gc.survey.Budget, 'size', new=measure), \
             patch.object(storage_git, 'snapshot', side_effect=recover), \
             patch('partyline.storage_worktrees.remove_directory', side_effect=remove), \
             patch.object(gc, 'remove_path', side_effect=remove_file):
            report = gc.cleanup(self.db)
        self.assertFalse(report['skipped'], report)
        self.assertTrue({'size', 'snapshot', 'delete'} <= set(observed))

    def test_line_cleanup_leaves_unrelated_homes_and_worktrees_untouched(self):
        target = self.child('target')
        unrelated = self.child('unrelated')
        target_home = self.att('target-owner', conv='target')
        other_home = self.att('unrelated-owner', conv='unrelated')
        with patch('partyline.storage_worktree_inventory.registrations',
                   side_effect=AssertionError('scoped cleanup must not inventory the repository')):
            report = gc.cleanup(self.db, line=self.db.get_conversation('target'))
        self.assertFalse(target.exists(), report)
        self.assertFalse(target_home.exists(), report)
        self.assertTrue(unrelated.exists())
        self.assertTrue((other_home / 'cache').exists())

    def test_clean_merged_worktrees_need_no_recovery_refs_on_either_path(self):
        automatic = self.child('merged-auto')
        manual = self.child('merged-manual')
        with patch.object(storage_git, 'snapshot', side_effect=AssertionError('unnecessary snapshot')):
            report = gc.cleanup(self.db, line=self.db.get_conversation('merged-auto'))
            self.assertFalse(automatic.exists(), report)
            self.assertEqual(cleanup_worktree(self.db, self.repo, str(manual), True), (True, None))
        self.assertEqual(git(self.repo, 'for-each-ref', '--format=%(refname)',
                              'refs/partyline/discarded'), '')

    def test_missing_merged_registration_needs_no_recovery_refs(self):
        path = self.child('merged-missing')
        shutil.rmtree(path)
        report = gc.cleanup(self.db, line=self.db.get_conversation('merged-missing'))
        self.assertIn(str(path), report['removed'])
        self.assertNotIn(str(path), git(self.repo, 'worktree', 'list', '--porcelain'))
        self.assertEqual(git(self.repo, 'for-each-ref', '--format=%(refname)',
                              'refs/partyline/discarded'), '')

    def test_fence_preservation_is_unlocked_and_final_removal_is_locked(self):
        name = next(iter(owners(self.db)))
        mirror = self.sessions / 'fence' / 'purged' / name
        mirror.parent.mkdir(parents=True)
        git(self.repo, 'clone', '--bare', '--no-hardlinks', self.repo, str(mirror))
        observed = []

        def recover(*args):
            self.assert_runtime_lock_free()
            observed.append('preserve')
            return preserve(*args)

        def remove(path):
            self.assert_runtime_lock_held()
            observed.append('remove')
            return gc.remove_path(path)

        with patch('partyline.storage_fences.preserve', side_effect=recover), \
             patch('partyline.storage_fences.remove_path', side_effect=remove):
            report = gc.cleanup(self.db)
        self.assertFalse(mirror.exists(), report)
        self.assertEqual(observed, ['preserve', 'remove'])

    async def test_startup_yields_and_reattaches_while_housekeeping_is_blocked(self):
        started, release, serving = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def housekeeping(*args, **kwargs):
            started.set()
            await release.wait()

        async def serve():
            async with server.lifespan(server.app):
                serving.set()
                await release.wait()

        automatic = AsyncMock()
        with patch.object(server.fence_probe, 'probe', return_value=(True, '', '')), \
             patch.object(server, 'engage_startup', side_effect=housekeeping), \
             patch.object(server, '_run_automatic_reattachment', automatic):
            lifetime = asyncio.create_task(serve())
            try:
                await started.wait()
                self.assertTrue(serving.is_set(), 'lifespan must yield before housekeeping completes')
                self.assertFalse(server.app.state.startup_housekeeping_task.done())
                await server.app.state.automatic_reattach_task
                automatic.assert_awaited_once()
            finally:
                release.set()
                await lifetime

    def test_purge_scopes_legacy_mirrors_and_finds_attachment_repositories(self):
        from partyline.git_fence import _mirror_dir

        self.child('legacy-line')
        other = self.sessions.parent / 'other'
        other.mkdir()
        git(other, 'init', '-q', '-b', 'main')
        git(other, 'commit', '--allow-empty', '-qm', 'base')
        self.att('legacy-owner', conv='legacy-line', cwd=str(other))
        common = git(other, 'rev-parse', '--path-format=absolute', '--git-common-dir')
        mirror = self.sessions / 'fence' / 'legacy-owner'
        mirror.mkdir(parents=True)
        target = _mirror_dir(common, 'legacy-owner')
        git(other, 'clone', '--bare', '--no-hardlinks', str(other), target)
        report = gc.cleanup(self.db, line=self.db.get_conversation('legacy-line'), purging=True)
        self.assertFalse(mirror.exists(), report)
        self.assertTrue(other.exists())
