"""Cleanup must reclaim durable content without needing space to copy it again."""

import errno
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from partyline import storage_cleanup as gc
from partyline.storage_removal import Failures, RetainedEntries, remove_contents
from tests.orchestrator_fixture import git
from tests.storage_cleanup_fixture import CleanupFixture


class CleanupPressureTest(CleanupFixture):
    def test_clean_merged_worktree_is_removed_without_a_space_reserve(self):
        path = self.child('clean-full-disk')
        with patch('shutil.disk_usage', return_value=SimpleNamespace(free=1)) as usage:
            report = gc.cleanup(self.db)
        usage.assert_not_called()
        self.assertFalse(path.exists(), report)
        self.assertFalse(report['skipped'])
        self.assertEqual(git(self.repo, 'for-each-ref', 'refs/partyline/discarded'), '')

    def test_large_committed_only_worktree_is_removed_near_zero_free_space(self):
        path = self.child('committed-full-disk')
        with (path / 'committed').open('wb') as stream:
            for _ in range(40):
                stream.write(b'x' * (1024 * 1024))
        git(path, 'add', 'committed')
        git(path, 'commit', '-qm', 'already durable')
        head = git(path, 'rev-parse', 'HEAD')
        with patch('shutil.disk_usage', return_value=SimpleNamespace(free=1)) as usage:
            report = gc.cleanup(self.db)
        usage.assert_not_called()
        self.assertFalse(path.exists(), report)
        self.assertIn(head, git(self.repo, 'for-each-ref', '--format=%(objectname)',
                                'refs/partyline/discarded'))

    def test_deletion_only_worktree_is_removed_near_zero_free_space(self):
        path = self.child('deleted-full-disk')
        for n in range(2100):
            (path / f'file-{n}').write_text('durable')
        git(path, 'add', '.')
        git(path, 'commit', '-qm', 'durable originals')
        for n in range(2100):
            (path / f'file-{n}').unlink()
        self.db.delete_conversation('deleted-full-disk')
        with patch('shutil.disk_usage', return_value=SimpleNamespace(free=1)):
            report = gc.cleanup(self.db)
        self.assertFalse(path.exists(), report)
        refs = git(self.repo, 'for-each-ref', '--format=%(refname)', 'refs/partyline/discarded').splitlines()
        snapshot = next(ref for ref in refs if ref.endswith('/snapshot'))
        self.assertEqual(git(self.repo, 'show', snapshot + '^:file-2099'), 'durable')

    def test_empty_plain_folder_does_not_check_disk_space(self):
        path = Path(self.repo) / '.partyline-worktrees' / 'empty'
        path.mkdir(parents=True)
        with patch('shutil.disk_usage', side_effect=AssertionError('nothing to recover')):
            report = gc.cleanup(self.db)
        self.assertFalse(path.exists(), report)


class RetainedCountTest(unittest.TestCase):
    def test_nonempty_parent_errors_do_not_count_as_denied_entries(self):
        failures = Failures()
        for n in range(30):
            for m in range(20):
                failures.add(f'root/cache-{n}/file-{m}.pyc', PermissionError(errno.EACCES, 'denied'))
            failures.add(f'root/cache-{n}/', OSError(errno.ENOTEMPTY, 'not empty'), directory=True)
        self.assertEqual(failures.count, 600)
        self.assertEqual(len(failures.directories), 30)
        self.assertIn('600 failures in 30 directories', failures.reason())

    def test_nonempty_without_a_denial_still_prevents_removing_the_checkout(self):
        def fail(folder, *, onerror):
            onerror(None, folder, (None, OSError(errno.ENOTEMPTY, 'contents changed'), None))

        with patch('partyline.storage_removal.os.scandir') as scan:
            entry = SimpleNamespace(name='new-work', path='/retiring/new-work', is_dir=lambda **_: True)
            scan.return_value.__enter__.return_value = [entry]
            with patch('partyline.storage_removal.shutil.rmtree', side_effect=fail):
                with self.assertRaises(RetainedEntries):
                    remove_contents('/retiring')
