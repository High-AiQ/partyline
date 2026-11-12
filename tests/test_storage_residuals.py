"""Pruned metadata, unreadable ignored content and persistent cleanup decisions."""

import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from partyline import storage_cleanup as gc
from tests.orchestrator_fixture import git
from tests.storage_cleanup_fixture import CleanupFixture


class ResidualCleanupTest(CleanupFixture):
    def refs(self, root=None):
        return git(root or self.repo, 'for-each-ref', '--format=%(refname)',
                   'refs/partyline/discarded').splitlines()

    def unreadable(self, path):
        blocked = path / 'browser-profile'
        blocked.mkdir()
        (blocked / 'private').write_text('unreadable only copy')
        (path / '.gitignore').write_text('browser-profile/\n')
        (path / 'readable').write_text('recover this')
        scan = os.scandir

        def deny(target):
            if str(target) == str(blocked):
                raise PermissionError(13, 'fixture unreadable', str(blocked))
            return scan(target)

        return blocked, patch('os.scandir', side_effect=deny)

    def test_dangling_nested_recovers_only_blobs_missing_from_surviving_owner(self):
        outer = self.child('outer')
        root = Path(self.directory.name) / 'owner'
        root.mkdir()
        git(root, 'init', '-q', '-b', 'main')
        (root / 'committed').write_bytes(b'already committed' * 65536)
        git(root, 'add', '.')
        git(root, 'commit', '-qm', 'durable')
        nested = outer / 'products'
        git(root, 'worktree', 'add', '-qb', 'line/products', str(nested))
        # The same content at another name must be recognized by blob, not path.
        (nested / 'committed').rename(nested / 'renamed')
        (nested / 'unique').write_text('only surviving copy')
        metadata = git(nested, 'rev-parse', '--absolute-git-dir')
        shutil.rmtree(metadata)
        self.db.delete_conversation('outer')
        report = gc.cleanup(self.db)
        self.assertFalse(outer.exists(), report)
        self.assertEqual(self.refs(), [])
        snapshot = next(ref for ref in self.refs(root) if ref.endswith('/snapshot'))
        self.assertEqual(git(root, 'ls-tree', '-r', '--name-only', snapshot), 'unique')
        self.assertEqual(git(root, 'show', snapshot + ':unique'), 'only surviving copy')

    def test_unreadable_ignored_worktree_recovers_readable_content_once(self):
        path = self.child('unreadable')
        blocked, denial = self.unreadable(path)
        with denial:
            report = gc.cleanup(self.db)
            refs = self.refs()
            again = gc.cleanup(self.db)
        self.assertFalse((path / 'readable').exists(), report)
        self.assertTrue((blocked / 'private').exists())
        self.assertEqual(self.refs(), refs)
        reason = next(row['reason'] for row in report['skipped'] if row['path'] == str(path))
        self.assertIn('cannot inspect', reason)
        self.assertNotIn('paths are ignored', reason)
        self.assertEqual(report['skipped'], again['skipped'])

    def test_plain_orphan_with_unreadable_ignored_directory_preserves_readable_files(self):
        path = Path(self.repo) / '.partyline-worktrees' / 'plain'
        path.mkdir(parents=True)
        blocked, denial = self.unreadable(path)
        with denial:
            report = gc.cleanup(self.db)
            refs = self.refs()
            gc.cleanup(self.db)
        self.assertFalse((path / 'readable').exists(), report)
        self.assertTrue((blocked / 'private').exists())
        self.assertEqual(self.refs(), refs)
        snapshot = next(ref for ref in refs if ref.endswith('/snapshot'))
        self.assertEqual(git(self.repo, 'show', snapshot + ':readable'), 'recover this')

    def test_noncache_ignored_files_are_kept_until_explicit_worktree_override(self):
        path = self.child('ignored')
        (path / '.gitignore').write_text('*.private\nnode_modules/\n')
        (path / 'only.private').write_text('important')
        (path / 'settings.private').write_text('config')
        cache = path / 'node_modules'
        cache.mkdir()
        (cache / 'package').write_text('cache')
        report = gc.cleanup(self.db)
        self.assertTrue((path / 'only.private').exists(), report)
        self.assertFalse(cache.exists(), 'known caches are cleared even while other ignored data is kept')
        reason = next(row['reason'] for row in report['skipped'] if row['path'] == str(path))
        self.assertIn('ignored files outside known caches', reason)
        self.assertIn('only.private', reason)
        self.assertIn('only.private (9 bytes)', reason)
        self.assertIn('settings.private (6 bytes)', reason)
        report = self.client.post('/api/storage/cleanup').json()
        self.assertTrue(path.exists(), report)
        report = self.client.post('/api/storage/cleanup', json={'remove_anyway': [str(path)]})
        self.assertEqual(report.status_code, 200, report.text)
        self.assertFalse(path.exists(), report.text)

    def test_second_start_skips_git_and_size_for_unchanged_kept_tree(self):
        path = self.child('independent')
        embed = path / 'embed'
        embed.mkdir()
        git(embed, 'init', '-q', '-b', 'main')
        report = gc.cleanup(self.db)
        self.assertTrue(path.exists(), report)
        from partyline.storage_survey import Budget
        from partyline.storage_worktrees import remove_worktree
        with patch.object(Budget, 'size') as sizing, \
             patch('partyline.storage_worktrees.remove_worktree') as inspecting:
            again = gc.cleanup(self.db)
        sizing.assert_not_called()
        inspecting.assert_not_called()
        self.assertEqual(again['skipped'], report['skipped'])
        (path / 'new').write_text('changed directory mtime')
        with patch('partyline.storage_worktrees.remove_worktree', wraps=remove_worktree) as retry:
            gc.cleanup(self.db)
        self.assertEqual(retry.call_count, 1)

    def test_known_ignored_caches_are_removed(self):
        path = self.child('caches')
        (path / '.gitignore').write_text(
            '.venv/\n__pycache__/\nnode_modules/\n.pytest_cache/\n.ruff_cache/\ndist/\n')
        for name in ('.venv', '__pycache__', 'node_modules', '.pytest_cache', '.ruff_cache', 'dist'):
            (path / name).mkdir()
            (path / name / 'generated').write_text('cache')
        report = gc.cleanup(self.db)
        self.assertFalse(path.exists(), report)

    @unittest.skipUnless(os.name == 'posix' and os.geteuid() != 0, 'requires non-root POSIX permissions')
    def test_real_unreadable_plain_folder_is_recovered_without_git_entering_denied_directory(self):
        path = Path(self.repo) / '.partyline-worktrees' / 'real-plain'
        path.mkdir(parents=True)
        blocked, _denial = self.unreadable(path)
        blocked.chmod(0)
        try:
            report = gc.cleanup(self.db)
            self.assertFalse((path / 'readable').exists(), report)
            refs = self.refs()
            gc.cleanup(self.db)
            self.assertEqual(self.refs(), refs)
        finally:
            blocked.chmod(0o755)
        self.assertTrue((blocked / 'private').exists())

    def test_noncache_override_cannot_delete_an_open_line_or_an_arbitrary_path(self):
        path = self.child('open', archived=False)
        (path / '.gitignore').write_text('*.private\n')
        (path / 'only.private').write_text('must remain')
        response = self.client.post('/api/storage/cleanup', json={
            'remove_anyway': [str(path), self.repo]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue((path / 'only.private').exists())
        self.actor = self.captain
        response = self.client.post('/api/storage/cleanup', json={'remove_anyway': [str(path)]})
        self.assertEqual(response.status_code, 403, response.text)

    def test_unchanged_ignored_decision_survives_database_reopen_and_ref_change_invalidates_it(self):
        from partyline.db import Db
        from partyline.storage_survey import Budget

        path = self.child('decision')
        (path / '.gitignore').write_text('*.private\n')
        (path / 'only.private').write_text('keep')
        first = gc.cleanup(self.db)
        reopened = Db(self.db.path)
        try:
            with patch.object(Budget, 'size') as sizing, \
                 patch('partyline.storage_worktrees.remove_worktree') as inspecting:
                again = gc.cleanup(reopened)
            sizing.assert_not_called()
            inspecting.assert_not_called()
            self.assertEqual(first, again)
        finally:
            reopened.close()
        git(path, 'commit', '--allow-empty', '-qm', 'new HEAD')
        from partyline.storage_worktrees import remove_worktree
        with patch('partyline.storage_worktrees.remove_worktree', wraps=remove_worktree) as inspecting:
            gc.cleanup(self.db)
        inspecting.assert_called_once()

    def test_dangling_committed_content_needs_no_recovery_space_or_new_refs(self):
        from types import SimpleNamespace

        path = self.child('committed-dangling')
        (path / 'content').write_text('already in owning store')
        git(path, 'add', '.')
        git(path, 'commit', '-qm', 'durable content')
        metadata = git(path, 'rev-parse', '--absolute-git-dir')
        (path / 'content').rename(path / 'other-name')
        shutil.rmtree(metadata)
        with patch('shutil.disk_usage', return_value=SimpleNamespace(free=1)) as space:
            report = gc.cleanup(self.db)
        self.assertFalse(path.exists(), report)
        self.assertEqual(self.refs(), [])
        space.assert_not_called()

    def test_partial_dangling_cleanup_keeps_ownership_hint_and_only_denied_subtree(self):
        path = self.child('partial-dangling')
        metadata = git(path, 'rev-parse', '--absolute-git-dir')
        shutil.rmtree(metadata)
        blocked, denial = self.unreadable(path)
        with denial:
            report = gc.cleanup(self.db)
        self.assertFalse((path / 'readable').exists(), report)
        self.assertTrue((path / '.git').is_file(), 'manual retry still needs its owning object store')
        self.assertTrue((blocked / 'private').exists())
        refs = self.refs()
        with patch('partyline.storage_worktrees.recover_dangling') as recovery:
            gc.cleanup(self.db)
        recovery.assert_not_called()
        self.assertEqual(refs, self.refs())

    def test_unavailable_nested_owner_keeps_content_in_place(self):
        path = self.child('missing-owner')
        nested = path / 'products'
        nested.mkdir()
        (nested / '.git').write_text('gitdir: ' + str(Path(self.directory.name) /
                                                    'missing/.git/worktrees/products1') + '\n')
        (nested / 'only-copy').write_text('must remain')
        report = gc.cleanup(self.db)
        self.assertTrue((nested / 'only-copy').exists(), report)
        self.assertEqual(self.refs(), [])

    def test_denied_plain_subtree_does_not_lose_symlinks_or_literal_path_names(self):
        path = Path(self.repo) / '.partyline-worktrees' / 'literal-plain'
        path.mkdir(parents=True)
        _blocked, denial = self.unreadable(path)
        literal = 'literal space.txt' if os.name == 'nt' else ':(glob)literal'
        (path / literal).write_text('literal name')
        try:
            (path / 'linked-folder').symlink_to('browser-profile', target_is_directory=True)
        except OSError:
            self.skipTest('symlink creation requires platform support or privileges')
        with denial:
            report = gc.cleanup(self.db)
        self.assertFalse((path / 'readable').exists(), report)
        snapshot = next(ref for ref in self.refs() if ref.endswith('/snapshot'))
        self.assertEqual(git(self.repo, 'show', snapshot + ':' + literal), 'literal name')
        self.assertEqual(git(self.repo, 'show', snapshot + ':linked-folder'), 'browser-profile')

    def test_dangling_recovery_preserves_raw_unique_bytes_without_git_clean_filters(self):
        import subprocess

        path = self.child('filtered-dangling')
        (path / '.gitattributes').write_text('*.txt text eol=lf\n')
        git(path, 'add', '.gitattributes')
        git(path, 'commit', '-qm', 'clean filter policy')
        (path / 'unique.txt').write_bytes(b'only copy\r\n')
        metadata = git(path, 'rev-parse', '--absolute-git-dir')
        shutil.rmtree(metadata)
        report = gc.cleanup(self.db)
        self.assertFalse(path.exists(), report)
        snapshot = next(ref for ref in self.refs() if ref.endswith('/snapshot'))
        content = subprocess.run(['git', 'show', snapshot + ':unique.txt'], cwd=self.repo,
                                 check=True, capture_output=True).stdout
        self.assertEqual(content, b'only copy\r\n')

    def test_raw_dangling_snapshot_handles_symlinks_and_quoted_names(self):
        import subprocess

        path = self.child('raw-names')
        name = 'space snowman ☃.txt' if os.name == 'nt' else 'space\t"\\\n☃.txt'
        (path / name).write_bytes(b'raw bytes\r\n')
        try:
            (path / 'link').symlink_to(name)
        except OSError:
            self.skipTest('symlink creation requires platform support or privileges')
        metadata = git(path, 'rev-parse', '--absolute-git-dir')
        shutil.rmtree(metadata)
        report = gc.cleanup(self.db)
        self.assertFalse(path.exists(), report)
        snapshot = next(ref for ref in self.refs() if ref.endswith('/snapshot'))
        for filename, content in ((name, b'raw bytes\r\n'), ('link', os.fsencode(name))):
            recovered = subprocess.run(['git', 'show', snapshot + ':' + filename], cwd=self.repo,
                                       check=True, capture_output=True).stdout
            self.assertEqual(recovered, content)
