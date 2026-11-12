"""Review regressions: durable blobs, narrow overrides and relevant decisions."""

import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

from partyline import storage_cleanup as gc
from partyline.storage_survey import Budget
from tests.orchestrator_fixture import git
from tests.storage_cleanup_fixture import CleanupFixture


class CleanupReviewRound2Test(CleanupFixture):
    def pruned(self, path):
        shutil.rmtree(git(path, 'rev-parse', '--absolute-git-dir'))

    def snapshots(self):
        return git(self.repo, 'for-each-ref', '--format=%(refname)',
                   'refs/partyline/discarded').splitlines()

    def test_staged_only_blob_is_anchored_before_removal_and_survives_gc(self):
        path = self.child('staged-only')
        (path / 'only-copy').write_text('staged but never committed')
        git(path, 'add', 'only-copy')
        oid = git(path, 'rev-parse', ':only-copy')
        self.pruned(path)
        with patch('shutil.disk_usage', return_value=SimpleNamespace(free=1)):
            report = gc.cleanup(self.db)
        self.assertFalse(path.exists(), report)
        refs = self.snapshots()
        self.assertTrue(refs, 'existing but unreachable blobs need a recovery ref')
        snapshot = next(ref for ref in refs if ref.endswith('/snapshot'))
        self.assertEqual(git(self.repo, 'rev-parse', snapshot + ':only-copy'), oid)
        git(self.repo, 'reflog', 'expire', '--expire=now', '--all')
        git(self.repo, 'gc', '--prune=now')
        self.assertEqual(git(self.repo, 'show', snapshot + ':only-copy'), 'staged but never committed')

    def test_detached_commit_blob_is_recovered_even_after_its_metadata_is_pruned(self):
        path = self.child('detached-only')
        git(path, 'checkout', '--detach', '-q')
        (path / 'only-copy').write_text('detached commit content')
        git(path, 'add', '.')
        git(path, 'commit', '-qm', 'detached')
        self.pruned(path)
        report = gc.cleanup(self.db)
        self.assertFalse(path.exists(), report)
        refs = self.snapshots()
        self.assertTrue(refs)
        snapshot = next(ref for ref in refs if ref.endswith('/snapshot'))
        git(self.repo, 'reflog', 'expire', '--expire=now', '--all')
        git(self.repo, 'gc', '--prune=now')
        self.assertEqual(git(self.repo, 'show', snapshot + ':only-copy'), 'detached commit content')

    def ignored(self, ident):
        path = self.child(ident)
        (path / '.gitignore').write_text('*.private\n')
        (path / 'only.private').write_text('must be chosen individually')
        return path

    def test_override_parent_or_unlisted_candidate_does_not_waive_ignored_policy(self):
        first, second = self.ignored('first'), self.ignored('second')
        # Neither an ancestor nor a candidate not yet offered as kept is consent.
        response = self.client.post('/api/storage/cleanup', json={
            'remove_anyway': [str(first.parent), str(first)]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(first.exists(), response.text)
        self.assertTrue(second.exists(), response.text)
        response = self.client.post('/api/storage/cleanup', json={'remove_anyway': [str(first)]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(first.exists(), response.text)
        self.assertTrue((second / 'only.private').exists(), response.text)

    def test_unrelated_merge_fetch_and_ref_packing_do_not_repeat_kept_tree_work(self):
        path = self.ignored('kept')
        first = gc.cleanup(self.db)
        git(self.repo, 'commit', '--allow-empty', '-qm', 'unrelated merge')
        tip = git(self.repo, 'rev-parse', 'HEAD')
        git(self.repo, 'update-ref', 'refs/remotes/origin/other', tip)
        git(self.repo, 'pack-refs', '--all', '--prune')
        with patch.object(Budget, 'size') as sizes, \
             patch('partyline.storage_worktrees.remove_worktree') as inspecting:
            again = gc.cleanup(self.db)
        sizes.assert_not_called()
        inspecting.assert_not_called()
        self.assertEqual(first['skipped'], again['skipped'])
        # An update of this tree's own packed branch is a relevant input.
        branch = git(path, 'symbolic-ref', 'HEAD')
        git(self.repo, 'update-ref', branch, tip)
        from partyline.storage_worktrees import remove_worktree
        with patch('partyline.storage_worktrees.remove_worktree', wraps=remove_worktree) as inspecting:
            gc.cleanup(self.db)
        inspecting.assert_called_once()

    def test_committed_crlf_checkout_uses_normalized_hash_without_copying_bytes(self):
        path = self.child('crlf')
        (path / '.gitattributes').write_bytes(b'*.txt text eol=lf\n')
        (path / 'content.txt').write_bytes(b'committed\n' * 65536)
        git(path, 'add', '.')
        git(path, 'commit', '-qm', 'normalized content')
        (path / 'content.txt').write_bytes(b'committed\r\n' * 65536)
        self.pruned(path)
        with patch('shutil.disk_usage', return_value=SimpleNamespace(free=1)) as space:
            report = gc.cleanup(self.db)
        self.assertFalse(path.exists(), report)
        self.assertEqual(self.snapshots(), [])
        space.assert_not_called()

    def test_surviving_owner_reachability_is_enumerated_once_for_multiple_pruned_trees(self):
        for ident in ('one', 'two'):
            path = self.child(ident)
            (path / 'only-copy').write_text(ident)
            git(path, 'add', '.')
            self.pruned(path)
        spawn = subprocess.Popen
        queries = []

        def count(args, *rest, **kwargs):
            if 'rev-list' in args and '--objects' in args:
                queries.append(args)
            return spawn(args, *rest, **kwargs)

        with patch('subprocess.Popen', side_effect=count):
            report = gc.cleanup(self.db)
        self.assertEqual(len(queries), 1, report)

    def test_listed_parent_entry_can_override_its_nested_worktree_but_not_a_sibling(self):
        parent = self.child('container')
        sibling = self.ignored('sibling')
        nested = parent / 'nested'
        git(self.repo, 'worktree', 'add', '-qb', 'line/nested', str(nested))
        (nested / '.gitignore').write_text('*.private\n')
        (nested / 'data.private').write_text('chosen with its containing entry')
        first = self.client.post('/api/storage/cleanup')
        self.assertEqual(first.status_code, 200, first.text)
        kept = next(item for item in first.json()['skipped'] if item['path'] == str(parent))
        self.assertTrue(kept['remove_anyway_allowed'])
        response = self.client.post('/api/storage/cleanup', json={'remove_anyway': [str(parent)]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(parent.exists(), response.text)
        self.assertTrue((sibling / 'only.private').exists(), response.text)

    def test_lfs_style_clean_hash_avoids_copying_committed_content_but_saves_unique_bytes_raw(self):
        from pathlib import Path
        import shlex
        import sys

        path = self.child('filtered')
        script = Path(self.directory.name) / 'clean.py'
        script.write_text('import hashlib,sys\n'
                          'data=sys.stdin.buffer.read()\n'
                          'print("version https://git-lfs.github.com/spec/v1")\n'
                          'print("oid sha256:"+hashlib.sha256(data).hexdigest())\n'
                          'print("size "+str(len(data)))\n')
        command = (subprocess.list2cmdline([sys.executable, str(script)]) if sys.platform == 'win32'
                   else shlex.join([sys.executable, str(script)]))
        git(self.repo, 'config', 'filter.fixture.clean', command)
        (path / '.gitattributes').write_bytes(b'*.bin filter=fixture\n')
        committed = b'already committed large file\0' * 32768
        (path / 'large.bin').write_bytes(committed)
        git(path, 'add', '.')
        git(path, 'commit', '-qm', 'pointer stored in Git')
        unique = b'new bytes\r\n\0'
        (path / 'unique.bin').write_bytes(unique)
        self.pruned(path)
        report = gc.cleanup(self.db)
        self.assertFalse(path.exists(), report)
        snapshot = next(ref for ref in self.snapshots() if ref.endswith('/snapshot'))
        names = git(self.repo, 'ls-tree', '-r', '--name-only', snapshot).splitlines()
        self.assertEqual(names, ['unique.bin'])
        saved = subprocess.run(['git', 'show', snapshot + ':unique.bin'], cwd=self.repo,
                               capture_output=True, check=True).stdout
        self.assertEqual(saved, unique)

    def test_exact_override_accepts_a_legacy_kept_entry_shown_in_inventory(self):
        from partyline.worktree_storage import record_kept

        path = self.ignored('legacy')
        record_kept(self.db, self.repo, str(path),
                    'ignored files outside known caches: only.private')
        inventory = self.client.get('/api/storage/details').json()
        item = next(item for item in inventory['kept'] if item['path'] == str(path))
        self.assertTrue(item['remove_anyway_allowed'])
        response = self.client.post('/api/storage/cleanup', json={'remove_anyway': [str(path)]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(path.exists(), response.text)
