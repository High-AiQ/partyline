"""Review regressions: bounded reports, event retries and actual reclaimed storage."""

import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from partyline import storage_cleanup as gc, storage_kept
from partyline.storage_details import details
from partyline.storage_fences import owners
from partyline.storage_routes import clean_all
from partyline.storage_survey import Budget
from tests.orchestrator_fixture import git
from tests.storage_cleanup_fixture import CleanupFixture


class CleanupReviewTest(CleanupFixture):
    def denied(self):
        path = self.child('denied')
        for n in range(30):
            folder = path / f'cache-{n}'
            folder.mkdir()
            for m in range(20):
                (folder / f'file-{m}.pyc').write_text('cache')
        (path / 'readable').write_text('recover then remove')
        return path

    def denial(self, path):
        unlink = os.unlink

        def fail(name, *args, **kwargs):
            if str(name).endswith('.pyc'):
                raise PermissionError(13, 'fixture denied', str(path / str(name)))
            return unlink(name, *args, **kwargs)

        return patch('os.unlink', side_effect=fail)

    def test_many_denials_have_a_bounded_reason_and_no_traceback(self):
        path = self.denied()
        with self.denial(path), self.assertLogs(gc.logger, 'WARNING') as logs:
            report = gc.cleanup(self.db)
        reason = next(row['reason'] for row in report['skipped'] if row['path'] == str(path))
        self.assertLess(len(reason), 2500)
        self.assertIn('600', reason)
        self.assertIn('cache-', reason)
        self.assertIn('.pyc', reason)
        self.assertNotIn('Traceback', '\n'.join(logs.output))
        self.assertFalse((path / 'readable').exists())
        self.assertEqual(next(row.reason for row in details(self.db).kept if row.path == str(path)), reason)

    def test_partial_cleanup_is_not_snapshotted_again_until_manual_retry(self):
        path = self.denied()
        with self.denial(path), patch.object(gc.logger, 'warning'):
            gc.cleanup(self.db)
            refs = git(self.repo, 'for-each-ref', 'refs/partyline/discarded')
            with patch('partyline.storage_worktrees.recover', side_effect=AssertionError('retried')):
                report = gc.cleanup(self.db)
        self.assertEqual(git(self.repo, 'for-each-ref', 'refs/partyline/discarded'), refs)
        self.assertTrue(path.exists(), report)
        self.assertTrue(any(row['path'] == str(path) for row in report['skipped']))
        clean_all(self.db)
        self.assertFalse(path.exists())

    @unittest.skipUnless(os.name == 'posix' and os.geteuid() != 0, 'requires POSIX permissions as non-root')
    def test_real_unwritable_directory_keeps_one_snapshot_until_manual_retry(self):
        path = self.child('real-permission')
        folder = path / 'cache'
        folder.mkdir()
        (folder / 'owned-by-container').write_text('keep until permissions repaired')
        (path / 'readable').write_text('recover then remove')
        folder.chmod(0o555)
        try:
            with self.assertLogs(gc.logger, 'WARNING'):
                report = gc.cleanup(self.db)
            refs = git(self.repo, 'for-each-ref', 'refs/partyline/discarded')
            gc.cleanup(self.db)
            self.assertEqual(git(self.repo, 'for-each-ref', 'refs/partyline/discarded'), refs)
            self.assertFalse((path / 'readable').exists(), report)
            self.assertTrue((folder / 'owned-by-container').exists())
        finally:
            folder.chmod(0o755)
        clean_all(self.db)
        self.assertFalse(path.exists())

    def test_insufficient_recovery_space_keeps_the_source_without_creating_objects(self):
        path = self.child('space')
        (path / 'only-copy').write_bytes(b'x' * 1024)
        objects = Path(self.repo) / '.git' / 'objects'
        before = Budget().size(objects)
        with patch('shutil.disk_usage', return_value=SimpleNamespace(free=1)):
            report = gc.cleanup(self.db)
        self.assertTrue((path / 'only-copy').exists(), report)
        self.assertEqual(Budget().size(objects), before)
        self.assertTrue(any('free space' in item['reason'] for item in report['skipped']))

    def test_recovery_estimate_streams_files_and_excludes_ignored_cache(self):
        from partyline.storage_recovery_space import RESERVE

        path = self.child('estimate')
        (path / 'only-copy').write_bytes(b'x' * 4096)
        objects = Path(self.repo) / '.git' / 'objects'
        before = Budget().size(objects)
        with patch('shutil.disk_usage', return_value=SimpleNamespace(free=RESERVE + 2048)):
            report = gc.cleanup(self.db)
        self.assertTrue((path / 'only-copy').exists(), report)
        self.assertEqual(Budget().size(objects), before)
        (path / 'only-copy').unlink()
        (path / '.gitignore').write_text('cache/\n')
        (path / 'cache').mkdir()
        (path / 'cache' / 'recreatable').write_bytes(b'x' * 65536)
        with patch('shutil.disk_usage', return_value=SimpleNamespace(free=RESERVE + 2048)):
            report = gc.cleanup(self.db)
        self.assertFalse(path.exists(), report)

    def test_kept_mirrors_are_summarized_per_line_without_sizing(self):
        name = next(iter(owners(self.db)))
        homes = []
        for n in range(50):
            ident = f'att-{n}'
            self.db.add_attachment(ident, 'root', ident, 'fake', ['fake'], self.repo)
            mirror = self.sessions / 'fence' / ident / name
            mirror.mkdir(parents=True)
            homes.append(str(mirror))
        broken = self.sessions / 'fence' / 'gone' / name
        broken.mkdir(parents=True)
        (broken / 'packed-refs').write_text('broken\n')
        measure = Budget.size

        def size(budget, path, *args):
            self.assertNotIn(str(path), homes)
            return measure(budget, path, *args)

        with patch.object(Budget, 'size', size):
            report = clean_all(self.db)
            listing = details(self.db)
        self.assertEqual(len(report['skipped']), 1)
        self.assertEqual(len(listing.kept), 1)
        self.assertEqual(report['retained_mirrors'][0]['count'], 50)
        self.assertEqual(listing.retained_mirrors[0].count, 50)
        self.assertEqual(len(report['retained_mirrors']), 1)

    def test_recovery_object_growth_is_deducted_from_reclaimed_bytes(self):
        path = Path(self.repo) / '.partyline-worktrees' / 'plain'
        path.mkdir(parents=True)
        (path / 'only-copy').write_bytes(os.urandom(2 * 1024 * 1024))
        objects = Path(self.repo) / '.git' / 'objects'
        before = Budget().size(objects)
        source = Budget().size(path)
        report = gc.cleanup(self.db)
        growth = Budget().size(objects) - before
        self.assertFalse(path.exists(), report)
        self.assertEqual(report['freed_bytes'], max(0, source - growth))

    def test_net_bytes_include_recovery_refs_and_removed_registration_metadata(self):
        path = self.child('compressible')
        (path / 'only-copy').write_bytes(b'x' * (2 * 1024 * 1024))
        common = Path(self.repo) / '.git'
        before = Budget().size(common)
        source = Budget().size(path)
        report = gc.cleanup(self.db)
        growth = Budget().size(common) - before
        self.assertFalse(path.exists(), report)
        self.assertEqual(report['freed_bytes'], max(0, source - growth))

    def mirror(self):
        name = next(iter(owners(self.db)))
        mirror = self.sessions / 'fence' / 'gone' / name
        mirror.parent.mkdir(parents=True)
        git(self.repo, 'clone', '--bare', '--no-hardlinks', self.repo, str(mirror))
        return mirror

    @unittest.skipUnless(os.name == 'posix' and os.geteuid() != 0, 'requires POSIX permissions as non-root')
    def test_real_unreadable_mirror_ref_pauses_until_manual_retry(self):
        mirror = self.mirror()
        git(mirror, 'update-ref', 'refs/heads/unreadable', 'HEAD')
        ref = mirror / 'refs' / 'heads' / 'unreadable'
        ref.chmod(0)
        try:
            gc.cleanup(self.db)
            reason = storage_kept.reason(self.db, mirror, suppressed_only=True)
            self.assertTrue(reason)
            with patch('partyline.storage_fences.preserve', side_effect=AssertionError('retried')):
                gc.cleanup(self.db)
        finally:
            ref.chmod(0o644)
        clean_all(self.db)
        self.assertFalse(mirror.exists())

    def test_retry_records_survive_reopen_and_migrations_are_idempotent(self):
        from partyline.db import Db

        path = Path(self.directory.name) / 'kept'
        path.mkdir()
        storage_kept.remember(self.db, path, 'permission denied', suppress_retry=True)
        reopened = Db(self.db.path)
        try:
            self.assertEqual(storage_kept.reason(reopened, path, suppressed_only=True), 'permission denied')
            storage_kept.remember(reopened, path, 'changed during recovery', suppress_retry=False)
            self.assertIsNone(storage_kept.reason(self.db, path, suppressed_only=True))
        finally:
            reopened.close()

    def test_transient_mirror_failures_are_retried_on_the_next_sweep(self):
        for error in (ValueError('mirror refs changed during recovery; retained'),
                      subprocess.TimeoutExpired('git', 30)):
            mirror = self.mirror()
            with patch('partyline.storage_fences.preserve', side_effect=error):
                report = gc.cleanup(self.db)
            self.assertTrue(mirror.exists(), report)
            report = gc.cleanup(self.db)
            self.assertFalse(mirror.exists(), report)

    def test_kept_records_are_pruned_after_external_removal(self):
        path = Path(self.directory.name) / 'vanished'
        path.mkdir()
        storage_kept.remember(self.db, path, 'permission denied')
        path.rmdir()
        gc.cleanup(self.db)
        self.assertIsNone(storage_kept.reason(self.db, path))
