"""Long-lived storage leftovers, protected owners, and durable Git recovery."""

import asyncio
import json
from pathlib import Path
import threading
import subprocess
from unittest.mock import AsyncMock, patch

from partyline import git_fence, storage_cleanup as gc, storage_survey
from partyline.line_worktree import place_child
from partyline.storage_details import details
from partyline.storage_routes import storage_router
from partyline.storage_worktrees import remove_worktree
from tests.orchestrator_fixture import TaskFixture, git


class CleanupTest(TaskFixture):
    def setUp(self):
        super().setUp()
        self.sessions = Path(self.directory.name) / 'sessions'
        for module, name, value in ((storage_survey, 'SESSIONS_ROOT', str(self.sessions)),
                                    (git_fence, 'FENCE_ROOT', str(self.sessions / 'fence'))):
            patcher = patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app.include_router(storage_router(self.runtime, lambda: self.sessions / 'media'))

    def att(self, ident, status='detached', session='session', conv='root', cwd=None):
        self.db.add_attachment(ident, conv, ident, 'fake', ['fake'], cwd or self.repo)
        self.db._exec('UPDATE attachments SET status=?,cli_session=? WHERE id=?', (status, session, ident))
        home = self.sessions / 'codex' / ident
        (home / 'cache').mkdir(parents=True)
        (home / 'cache' / 'remote_plugin_catalog').write_bytes(b'x' * 100)
        (home / 'session.jsonl').write_text('resumable')
        folder = Path(self.db.path + '.agent-connections')
        folder.mkdir(exist_ok=True)
        (folder / (ident + '.json')).write_text('connection')
        (folder / (ident + '.mcp.json')).write_text('config')
        return home

    def plan(self, ids):
        self.db._exec("INSERT INTO restart_plan(singleton,conversation_id,token,attachment_ids,"
                      "debrief,created_at) VALUES(1,'root','t',?,'',0)", (json.dumps(ids),))

    def child(self, ident, archived=True):
        self.db.create_conversation(ident, ident)
        self.db._exec("UPDATE conversations SET parent_id='root',captain_mode='manager_tree' WHERE id=?",
                      (ident,))
        placed = place_child(self.db, 'root', ident)
        if archived:
            self.db.archive_conversation(ident)
        return Path(placed['cwd'])

    def test_hundreds_of_old_homes_and_retired_rows_are_revisited(self):
        for n in range(220):
            ident = f'old-{n}'
            self.db.create_conversation(ident, ident)
            self.db.archive_conversation(ident)
            self.att(ident, conv=ident)
        resumable = self.att('resume')
        fresh = self.att('fresh', session=None)
        orphan = self.sessions / 'pi' / 'lost'
        orphan.mkdir(parents=True)
        (orphan / 'cache').mkdir()
        report = gc.cleanup(self.db)
        self.assertGreater(report['freed_bytes'], 22000)
        self.assertEqual(list((self.sessions / 'codex').iterdir()), [resumable])
        self.assertFalse((resumable / 'cache').exists())
        self.assertTrue((resumable / 'session.jsonl').exists())
        self.assertFalse(fresh.exists())
        self.assertFalse(orphan.exists())
        self.assertEqual(list(Path(self.db.path + '.agent-connections').iterdir()), [])

    def test_starting_running_and_restart_plan_keep_every_file(self):
        homes = [self.att('starting', 'starting'), self.att('running', 'running'), self.att('planned')]
        self.plan(['planned'])
        path = self.child('retired')
        self.att('in-tree', cwd=str(path))
        self.db._exec("UPDATE restart_plan SET attachment_ids=?", (json.dumps(['planned', 'in-tree']),))
        report = gc.cleanup(self.db)
        for home in homes:
            self.assertTrue((home / 'cache' / 'remote_plugin_catalog').exists())
            self.assertTrue(Path(self.db.path + '.agent-connections', home.name + '.json').exists())
            self.assertTrue(Path(self.db.path + '.agent-connections', home.name + '.mcp.json').exists())
        self.assertTrue(path.exists())
        self.assertTrue(any('restart plan' in item['reason'] for item in report['skipped']))

    def test_git_recovery_contains_working_and_staged_files_before_directory_goes(self):
        path = self.child('dirty')
        (path / 'uncommitted').write_text('the only copy')
        (path / 'staged').write_text('index contents')
        git(path, 'add', 'staged')
        (path / 'staged').write_text('working contents')
        from partyline.retirement_worktree import remove_directory
        observed = []

        def remove(where, root):
            refs = git(root, 'for-each-ref', '--format=%(refname)', 'refs/partyline/discarded').splitlines()
            snapshots = [ref for ref in refs if ref.endswith('/snapshot')]
            self.assertTrue(snapshots)
            self.assertEqual(git(root, 'show', snapshots[-1] + ':uncommitted'), 'the only copy')
            self.assertEqual(git(root, 'show', snapshots[-1] + ':staged'), 'working contents')
            index = next(ref for ref in refs if ref.endswith('/index'))
            self.assertEqual(git(root, 'show', index + ':staged'), 'index contents')
            observed.append(where)
            remove_directory(where, root)

        with patch('partyline.storage_worktrees.remove_directory', side_effect=remove):
            report = gc.cleanup(self.db)
        self.assertEqual(observed, [str(path)])
        self.assertIn(str(path), report['removed'])
        self.assertFalse(path.exists())

    def test_orphan_unmerged_commit_and_unregistered_folder_are_preserved_and_removed(self):
        path = self.child('lost')
        git(path, 'commit', '--allow-empty', '-qm', 'unmerged orphan')
        head = git(path, 'rev-parse', 'HEAD')
        self.db.delete_conversation('lost')
        plain = Path(self.repo) / '.partyline-worktrees' / 'unregistered'
        plain.mkdir()
        (plain / 'unique').write_text('lost directory content')
        report = gc.cleanup(self.db)
        self.assertFalse(path.exists(), report)
        self.assertFalse(plain.exists(), report)
        refs = git(self.repo, 'for-each-ref', '--format=%(objectname)', 'refs/partyline/discarded')
        self.assertIn(head, refs)
        tips = git(self.repo, 'for-each-ref', '--format=%(refname)', 'refs/partyline/discarded').splitlines()
        self.assertTrue(any(subprocess.run(['git', 'show', ref + ':unique'], cwd=self.repo,
                                           capture_output=True,
                                           text=True).stdout.strip() == 'lost directory content'
                            for ref in tips))

    def test_independent_nested_clone_is_reported_without_touching_it(self):
        path = self.child('nested')
        nested = path / 'independent'
        nested.mkdir()
        git(nested, 'init', '-q', '-b', 'main')
        git(nested, '-c', 'user.name=test', '-c', 'user.email=test@local', 'commit',
            '--allow-empty', '-qm', 'only here')
        report = gc.cleanup(self.db)
        self.assertTrue(nested.exists())
        self.assertTrue(any('independent nested repository' in item['reason'] for item in report['skipped']))

    def test_rechecks_status_and_new_owner_after_enumeration(self):
        home = self.att('racing', session=None)
        original = gc.attachment_reason
        reads = []

        def reason(db, ident):
            reads.append(ident)
            if len(reads) == 2:
                self.db._exec("UPDATE attachments SET status='starting' WHERE id='racing'")
            return original(db, ident)

        with patch.object(gc, 'attachment_reason', side_effect=reason):
            gc.cleanup(self.db, attachment_id='racing')
        self.assertTrue(home.exists())
        path = self.child('adopted')
        self.db.restore_conversation('adopted')
        self.assertEqual(remove_worktree(self.db, self.repo, str(path)), 'belongs to an open line')

    def test_failure_logs_and_continues_and_all_walks_run_in_a_thread(self):
        broken = self.att('broken', session=None)
        good = self.att('good', session=None)
        remove = gc.remove_path
        threads = []

        def fail_one(path):
            threads.append(threading.get_ident())
            if Path(path) == broken:
                raise OSError('unreadable')
            remove(path)

        with patch.object(gc, 'remove_path', side_effect=fail_one), self.assertLogs(gc.logger, 'ERROR'):
            report = asyncio.run(gc.automatic(self.db))
        self.assertTrue(broken.exists())
        self.assertFalse(good.exists())
        self.assertNotIn(threading.get_ident(), threads)
        self.assertTrue(any('unreadable' in item['reason'] for item in report['skipped']))

    def test_people_only_one_click_and_idle_lines_are_flagged_never_retired(self):
        path = self.child('idle', archived=False)
        self.db._exec("UPDATE conversations SET created_at=0 WHERE id='idle'")
        listing = details(self.db, now=15 * 86400)
        self.assertIn('idle', [line.id for line in listing.idle_lines])
        self.actor = self.captain
        self.assertEqual(self.client.post('/api/storage/cleanup').status_code, 403)
        self.assertEqual(self.client.get('/api/storage/details').status_code, 403)
        self.actor = self.human
        home = self.att('fresh', session=None)
        response = self.client.post('/api/storage/cleanup')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(home.exists())
        self.assertTrue(path.exists())
        self.assertIsNone(self.db.get_conversation('idle')['archived_at'])

    def test_startup_and_stops_call_cleanup_off_the_event_loop(self):
        from partyline.runtime import ChatRuntime
        home = self.att('stopping', status='running')
        # Exercise the actual adapter status callback without starting a pty.
        owner = self.db.get_attachment('stopping')['runtime_owner']
        runtime = ChatRuntime(self.db)
        runtime.broadcast_attachment = AsyncMock()
        asyncio.run(runtime.status_callback('stopping', 'root', owner)('exited'))
        self.assertFalse((home / 'cache').exists())

    def test_nested_linked_worktree_is_recovered_and_removed_via_its_owner(self):
        path = self.child('linked')
        other = Path(self.directory.name) / 'other'
        other.mkdir()
        git(other, 'init', '-q', '-b', 'main')
        git(other, 'commit', '--allow-empty', '-qm', 'base')
        nested = path / 'nested'
        git(other, 'worktree', 'add', '-b', 'line/linked', str(nested))
        (nested / 'only-copy').write_text('nested dirt')
        report = gc.cleanup(self.db)
        self.assertFalse(path.exists(), report)
        refs = git(other, 'for-each-ref', '--format=%(refname)', 'refs/partyline/discarded').splitlines()
        snapshot = next(ref for ref in refs if ref.endswith('/snapshot'))
        self.assertEqual(git(other, 'show', snapshot + ':only-copy'), 'nested dirt')
        self.assertNotIn(str(nested), git(other, 'worktree', 'list', '--porcelain'))

    def test_purged_line_mirror_unpublished_refs_are_anchored_before_removal(self):
        from partyline.git_fence_root import refresh
        path = self.child('mirror')
        common = git(self.repo, 'rev-parse', '--path-format=absolute', '--git-common-dir')
        gitdir = git(path, 'rev-parse', '--absolute-git-dir')
        mirror = Path(git_fence.refresh_mirror(common, gitdir, 'mirror'))
        refresh(common, str(mirror))
        git(path, 'commit', '--allow-empty', '-qm', 'unpublished')
        tip = git(path, 'rev-parse', 'HEAD')
        target = mirror / 'refs' / 'heads' / 'line' / 'mirror'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(tip + '\n')
        # Host branch still points at the base; only the mirror names the new commit.
        base = git(self.repo, 'rev-parse', 'main')
        git(self.repo, 'update-ref', 'refs/heads/line/mirror', base)
        report = gc.cleanup(self.db, line=self.db.get_conversation('mirror'))
        self.assertFalse(mirror.exists(), report)
        self.assertIn(tip, git(self.repo, 'for-each-ref', '--format=%(objectname)',
                               'refs/partyline/discarded'))

    def test_mirror_with_unknown_owner_is_reported_and_kept(self):
        mirror = self.sessions / 'fence' / 'lost' / 'git-unknown'
        mirror.mkdir(parents=True)
        (mirror / 'packed-refs').write_text('do not discard')
        report = gc.cleanup(self.db)
        self.assertTrue(mirror.exists())
        self.assertTrue(any('owning repository is unavailable' in item['reason']
                            for item in report['skipped']))

    def test_missing_orphan_registration_keeps_detached_commit_before_pruning(self):
        import shutil

        path = self.child('missing')
        git(path, 'checkout', '--detach', '-q')
        git(path, 'commit', '--allow-empty', '-qm', 'only detached HEAD')
        tip = git(path, 'rev-parse', 'HEAD')
        self.db.delete_conversation('missing')
        shutil.rmtree(path)
        report = gc.cleanup(self.db)
        self.assertIn(str(path), report['removed'])
        self.assertNotIn(str(path), git(self.repo, 'worktree', 'list', '--porcelain'))
        self.assertIn(tip, git(self.repo, 'for-each-ref', '--format=%(objectname)',
                               'refs/partyline/discarded'))

    def test_new_start_during_snapshot_prevents_worktree_deletion(self):
        from partyline.storage_git import recover

        path = self.child('racy-tree')
        self.att('racy-owner', conv='racy-tree', cwd=str(path))

        def start_after_snapshot(*args):
            before = recover(*args)
            self.db._exec("UPDATE attachments SET status='starting' WHERE id='racy-owner'")
            return before

        with patch('partyline.storage_worktrees.recover', side_effect=start_after_snapshot):
            report = gc.cleanup(self.db)
        self.assertTrue(path.exists())
        self.assertTrue(any(item['path'] == str(path) and 'running' in item['reason']
                            for item in report['skipped']))

    def test_purged_line_mirror_with_restart_plan_is_untouched(self):
        from partyline.git_fence_root import refresh

        path = self.child('planned-mirror')
        self.att('mirror-owner', conv='planned-mirror', cwd=str(path))
        self.plan(['mirror-owner'])
        common = git(self.repo, 'rev-parse', '--path-format=absolute', '--git-common-dir')
        mirror = Path(git_fence.refresh_mirror(common, git(path, 'rev-parse', '--absolute-git-dir'),
                                              'planned-mirror'))
        refresh(common, str(mirror))
        report = gc.cleanup(self.db, line=self.db.get_conversation('planned-mirror'))
        self.assertTrue(mirror.exists(), report)
        self.assertTrue(path.exists())

    def test_mirror_only_objects_are_copied_not_just_named(self):
        from partyline.storage_fences import owners

        mirror_name = next(iter(owners(self.db)))
        mirror = self.sessions / 'fence' / 'purged' / mirror_name
        mirror.parent.mkdir(parents=True)
        git(self.repo, 'clone', '--bare', '--no-hardlinks', self.repo, str(mirror))
        tree = git(mirror, 'rev-parse', 'HEAD^{tree}')
        unique = git(mirror, 'commit-tree', tree, '-p', 'HEAD', '-m', 'mirror-only commit')
        git(mirror, 'update-ref', 'refs/heads/only-mirror', unique)
        self.assertNotEqual(subprocess.run(['git', 'cat-file', '-e', unique], cwd=self.repo,
                                          capture_output=True).returncode, 0)
        report = gc.cleanup(self.db)
        self.assertFalse(mirror.exists(), report)
        refs = git(self.repo, 'for-each-ref', '--format=%(objectname) %(refname)',
                   'refs/partyline/discarded').splitlines()
        recovery = next(row.split(' ', 1)[1] for row in refs if row.startswith(unique + ' '))
        self.assertEqual(git(self.repo, 'log', '-1', '--format=%s', recovery), 'mirror-only commit')

    def test_unpublished_extra_mirror_ref_is_anchored(self):
        from partyline.storage_fences import owners

        name = next(iter(owners(self.db)))
        mirror = self.sessions / 'fence' / 'purged' / name
        mirror.parent.mkdir(parents=True)
        git(self.repo, 'clone', '--bare', '--no-hardlinks', self.repo, str(mirror))
        unique = git(self.repo, 'commit-tree', git(self.repo, 'rev-parse', 'HEAD^{tree}'),
                     '-p', 'HEAD', '-m', 'unpublished extra ref')
        git(mirror, 'fetch', self.repo, unique)
        git(mirror, 'update-ref', 'refs/heads/extra', unique)
        report = gc.cleanup(self.db)
        self.assertFalse(mirror.exists(), report)
        self.assertIn(unique, git(self.repo, 'for-each-ref', '--format=%(objectname)',
                                  'refs/partyline/discarded'))

    def test_startup_cleanup_runs_in_thread_and_a_failed_step_does_not_stop_worktrees(self):
        from partyline.startup_state import engage_startup

        path = self.child('startup')
        main = threading.get_ident()
        seen = []

        def fail_attachments(*args):
            seen.append(threading.get_ident())
            raise OSError('attachment walk failed')

        with patch('partyline.startup_state.post_interruption_notices', new_callable=AsyncMock), \
             patch('partyline.startup_state.reap_legacy_temp'), \
             patch('partyline.startup_state.reap_previous_tmp_root'), \
             patch('partyline.retirement_evidence.pack_stored'), \
             patch('partyline.scope_sweep.sweep_empty_scopes'), \
             patch.object(gc, 'clean_attachments', side_effect=fail_attachments), \
             self.assertLogs(gc.logger, 'ERROR'):
            asyncio.run(engage_startup(self.runtime))
        self.assertTrue(seen)
        self.assertNotIn(main, seen)
        self.assertFalse(path.exists())

    def test_purge_refuses_to_drop_restart_plan_ownership_records(self):
        from fastapi import HTTPException
        from partyline.conversation_purge import execute_purge

        path = self.child('planned-purge')
        self.att('restart-owner', conv='planned-purge', cwd=str(path))
        self.plan(['restart-owner'])
        with self.assertRaises(HTTPException) as error:
            asyncio.run(execute_purge(self.runtime, None, self.db,
                                     self.db.get_conversation('planned-purge')))
        self.assertEqual(error.exception.status_code, 409)
        self.assertTrue(path.exists())
        self.assertIsNotNone(self.db.get_attachment('restart-owner'))

    def test_restored_line_reclassifies_whole_home_to_cache_at_deletion(self):
        path = self.child('restoring')
        home = self.att('restored-owner', conv='restoring', cwd=str(path))
        original = gc.attachment_reason
        reads = []

        def restore(db, ident):
            reads.append(ident)
            if len(reads) == 2:
                self.db.restore_conversation('restoring')
            return original(db, ident)

        with patch.object(gc, 'attachment_reason', side_effect=restore):
            gc.cleanup(self.db, attachment_id='restored-owner')
        self.assertTrue((home / 'session.jsonl').exists())
        self.assertFalse((home / 'cache').exists())
