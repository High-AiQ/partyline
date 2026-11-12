"""Real-host cleanup failures, reproduced entirely in temporary repositories."""

import os
from pathlib import Path
import subprocess
import time
from unittest.mock import patch

from partyline import git_fence, storage_cleanup as gc
from partyline.storage_fences import clean_fences, owners
from tests.orchestrator_fixture import git
from tests.storage_cleanup_fixture import CleanupFixture


class CleanupGapsTest(CleanupFixture):
    def nested(self, parent, name='products'):
        root = Path(self.directory.name) / name
        root.mkdir()
        git(root, 'init', '-q', '-b', 'main')
        git(root, 'commit', '--allow-empty', '-qm', 'base')
        path = parent / name
        git(root, 'worktree', 'add', '-qb', 'line/' + name, str(path))
        return root, path

    def test_nested_second_repository_and_deeper_worktree_recover_innermost(self):
        parent = self.child('outer')
        root, nested = self.nested(parent)
        deep_root, deep = self.nested(nested, 'deeper')
        for path in (nested, deep):
            (path / 'unique').write_text('unmerged')
            git(path, 'add', 'unique')
            git(path, 'commit', '-qm', 'unmerged')
            (path / 'unique').write_text('uncommitted')
        self.db.delete_conversation('outer')
        report = gc.cleanup(self.db)
        self.assertFalse(parent.exists(), report)
        for repo in (root, deep_root):
            refs = git(repo, 'for-each-ref', '--format=%(refname)', 'refs/partyline/discarded').splitlines()
            snapshot = next(ref for ref in refs if ref.endswith('/snapshot'))
            self.assertEqual(git(repo, 'show', snapshot + ':unique'), 'uncommitted')
            self.assertEqual(git(repo, 'show', snapshot + '^:unique'), 'unmerged')

    def test_large_orphan_recovery_has_all_files_and_deletions(self):
        path = self.child('large')
        for n in range(2100):
            (path / f'file-{n}').write_text('committed')
        git(path, 'add', '.')
        git(path, 'commit', '-qm', 'many files')
        for n in range(2100):
            (path / f'file-{n}').unlink()
            (path / f'new-{n}').write_text(f'only copy {n}')
        self.db.delete_conversation('large')
        report = gc.cleanup(self.db)
        self.assertFalse(path.exists(), report)
        refs = git(self.repo, 'for-each-ref', '--format=%(refname)', 'refs/partyline/discarded').splitlines()
        snapshot = next(ref for ref in refs if ref.endswith('/snapshot'))
        names = git(self.repo, 'ls-tree', '-r', '--name-only', snapshot).splitlines()
        self.assertEqual(len([n for n in names if n.startswith('new-')]), 2100)
        self.assertNotIn('file-0', names)
        self.assertEqual(git(self.repo, 'show', snapshot + ':new-2099'), 'only copy 2099')
        self.assertEqual(git(self.repo, 'show', snapshot + '^:file-2099'), 'committed')

    def test_unremovable_entry_keeps_reason_but_removes_other_content(self):
        path = self.child('permissions')
        blocked = path / '__pycache__'
        blocked.mkdir()
        locked = blocked / 'locked.pyc'
        locked.write_text('cache')
        (path / 'removable').write_text('save then remove')
        unlink = os.unlink

        def deny(name, *args, **kwargs):
            if str(name).endswith('locked.pyc'):
                raise PermissionError(13, 'fixture denies removal', str(locked))
            return unlink(name, *args, **kwargs)

        with patch('os.unlink', side_effect=deny):
            report = gc.cleanup(self.db)
        self.assertTrue(locked.exists())
        self.assertFalse((path / 'removable').exists(), report)
        self.assertTrue((path / '.git').exists())
        reason = ' '.join(item['reason'] for item in report['skipped'])
        self.assertIn('locked.pyc', reason)
        self.actor = self.human
        kept = self.client.get('/api/storage/details').json()['kept']
        self.assertTrue(any('locked.pyc' in item['reason'] for item in kept))

    def test_unreadable_subtree_stays_while_readable_work_is_recovered(self):
        path = self.child('unreadable')
        blocked = path / 'container-output'
        blocked.mkdir()
        (blocked / 'only-copy').write_text('must remain')
        (path / 'readable').write_text('recover me')
        scan = os.scandir

        def deny(target):
            if str(target) == str(blocked):
                raise PermissionError(13, 'fixture cannot inspect', str(blocked))
            return scan(target)

        with patch('os.scandir', side_effect=deny):
            report = gc.cleanup(self.db)
        self.assertTrue((blocked / 'only-copy').exists())
        self.assertFalse((path / 'readable').exists(), report)
        self.assertTrue(any(str(blocked) in item['reason'] for item in report['skipped']))
        refs = git(self.repo, 'for-each-ref', '--format=%(refname)', 'refs/partyline/discarded').splitlines()
        snapshot = next(ref for ref in refs if ref.endswith('/snapshot'))
        self.assertEqual(git(self.repo, 'show', snapshot + ':readable'), 'recover me')

    def test_unreadable_fence_folder_does_not_stop_the_next_folder(self):
        name = next(iter(owners(self.db)))
        blocked = self.sessions / 'fence' / 'a-blocked'
        blocked.mkdir(parents=True)
        (blocked / name).mkdir()
        good = self.sessions / 'fence' / 'z-good' / name
        good.parent.mkdir()
        git(self.repo, 'clone', '--bare', '--no-hardlinks', self.repo, str(good))
        listing = Path.iterdir

        def deny(target):
            if target == blocked:
                raise PermissionError(13, 'fixture cannot list mirrors', str(blocked))
            return listing(target)

        with patch.object(Path, 'iterdir', deny):
            report = gc.cleanup(self.db)
            self.actor = self.human
            kept = self.client.get('/api/storage/details').json()['kept']
        self.assertFalse(good.exists(), report)
        self.assertTrue(any(item['path'] == str(blocked) for item in report['skipped']))
        self.assertTrue(any(item['path'] == str(blocked) for item in kept))

    def test_legacy_refs_overlay_is_readable_without_head_or_objects(self):
        path = self.child('mirror-origin', archived=False)
        common = git(self.repo, 'rev-parse', '--path-format=absolute', '--git-common-dir')
        mirror = Path(git_fence.refresh_mirror(common, git(path, 'rev-parse', '--absolute-git-dir'), 'gone'))
        self.assertFalse((mirror / 'HEAD').exists())
        self.assertFalse((mirror / 'objects').exists())
        report = gc.cleanup(self.db)
        self.assertFalse(mirror.exists(), report)

    def test_unreadable_mirror_is_reported_and_not_retried_on_startup(self):
        name = next(iter(owners(self.db)))
        mirror = self.sessions / 'fence' / 'gone' / name
        mirror.mkdir(parents=True)
        (mirror / 'packed-refs').write_text('invalid packed ref\n')
        report = gc.cleanup(self.db)
        self.assertTrue(mirror.exists())
        self.assertTrue(any('mirror' in item['reason'] for item in report['skipped']))
        with patch('partyline.storage_fences.preserve', side_effect=AssertionError('retried')):
            again = gc.cleanup(self.db)
        self.assertEqual(report['skipped'], again['skipped'])
        self.actor = self.human
        kept = self.client.get('/api/storage/details').json()['kept']
        self.assertTrue(any(item['path'] == str(mirror) for item in kept))

    def test_manual_cleanup_retries_a_repaired_mirror(self):
        name = next(iter(owners(self.db)))
        mirror = self.sessions / 'fence' / 'gone' / name
        mirror.mkdir(parents=True)
        (mirror / 'packed-refs').write_text('broken\n')
        gc.cleanup(self.db)
        (mirror / 'packed-refs').unlink()
        self.actor = self.human
        report = self.client.post('/api/storage/cleanup').json()
        self.assertFalse(mirror.exists(), report)
        self.assertIn(str(mirror), report['removed'])

    def test_broken_loose_ref_is_kept_even_when_git_only_warns(self):
        name = next(iter(owners(self.db)))
        mirror = self.sessions / 'fence' / 'gone' / name
        (mirror / 'refs' / 'heads').mkdir(parents=True)
        (mirror / 'refs' / 'heads' / 'broken').write_text('not-a-tip\n')
        report = gc.cleanup(self.db)
        self.assertTrue(mirror.exists(), report)
        self.assertTrue(any('broken' in item['reason'] for item in report['skipped']))

    def test_staged_only_work_is_recovered_when_working_tree_matches_head(self):
        path = self.child('index-only')
        (path / 'only-staged').write_text('staged content')
        git(path, 'add', 'only-staged')
        (path / 'only-staged').unlink()
        report = gc.cleanup(self.db)
        self.assertFalse(path.exists(), report)
        refs = git(self.repo, 'for-each-ref', '--format=%(refname)', 'refs/partyline/discarded').splitlines()
        index = next(ref for ref in refs if ref.endswith('/index'))
        self.assertEqual(git(self.repo, 'show', index + ':only-staged'), 'staged content')

    def test_one_orphan_does_not_probe_every_retained_managed_checkout(self):
        name = next(iter(owners(self.db)))
        for n in range(60):
            ident = f'kept-{n}'
            cwd = Path(self.repo) / '.partyline-worktrees' / ident
            cwd.mkdir(parents=True)
            self.db.add_attachment(ident, 'root', ident, 'fake', ['fake'], str(cwd))
            (self.sessions / 'fence' / ident / name).mkdir(parents=True)
        orphan = self.sessions / 'fence' / 'orphan' / name
        orphan.parent.mkdir()
        git(self.repo, 'clone', '--bare', '--no-hardlinks', self.repo, str(orphan))
        report = gc.result()
        run = subprocess.run
        with patch('subprocess.run', wraps=run) as calls:
            clean_fences(self.db, report)
        self.assertFalse(orphan.exists(), report)
        self.assertLess(calls.call_count, 20)
        self.assertEqual(len(report['skipped']), 0)
        self.assertEqual(report['retained_mirrors'][0]['count'], 60)

    def test_3000_retained_mirrors_do_not_spawn_git_per_attachment(self):
        name = next(iter(owners(self.db)))
        for n in range(3000):
            ident = f'owner-{n}'
            self.db.add_attachment(ident, 'root', ident, 'fake', ['fake'], self.repo)
            (self.sessions / 'fence' / ident / name).mkdir(parents=True)
        run = subprocess.run
        calls = []

        def count(*args, **kwargs):
            calls.append(args[0])
            return run(*args, **kwargs)

        report = gc.result()
        start = time.perf_counter()
        with patch('subprocess.run', side_effect=count):
            clean_fences(self.db, report)
        elapsed = time.perf_counter() - start
        print(f'3000 retained mirrors: {elapsed:.3f}s, {len(calls)} subprocesses', flush=True)
        self.assertEqual(len(calls), 0)
        self.assertEqual(len(report['skipped']), 0)
        self.assertEqual(report['retained_mirrors'][0]['count'], 3000)
