"""Storage usage and clearing: only regenerable, unused data is ever removed."""

import json
import os
from unittest.mock import patch

from partyline import attachment_tmp, storage_survey
from partyline.orchestrator_contracts import ReviewRequestIn
from partyline.orchestrator_service import request_review
from partyline.storage_routes import storage_router
from tests.orchestrator_fixture import TaskFixture, git


class StorageTest(TaskFixture):
    def setUp(self):
        super().setUp()
        self.sessions = os.path.join(self.directory.name, 'sessions')
        self.tmp_base = os.path.join(self.directory.name, 'tmpbase')
        for patcher in (patch.object(storage_survey, 'SESSIONS_ROOT', self.sessions),
                        patch.dict(os.environ, {'PARTYLINE_TMP_BASE': self.tmp_base})):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.media = os.path.join(self.directory.name, 'media')
        os.makedirs(self.media)
        with open(os.path.join(self.media, 'pic.png'), 'wb') as handle:
            handle.write(b'm' * 321)
        self.app.include_router(storage_router(self.runtime, lambda: self.media))

    def att(self, ident, status='detached', cli_session=None, cwd=None):
        self.db.add_attachment(ident, 'root', ident, 'fake', ['fake'], cwd or self.repo)
        self.db._exec('UPDATE attachments SET status=?,cli_session=? WHERE id=?',
                      (status, cli_session, ident))

    def plan(self, ids):
        self.db._exec("INSERT INTO restart_plan(singleton,conversation_id,token,attachment_ids,"
                      "debrief,created_at) VALUES(1,'root','t',?, '', 0)", (json.dumps(ids),))

    def fill(self, path, size=1000):
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, 'blob'), 'wb') as handle:
            handle.write(b'x' * size)

    def clear(self, key):
        self.actor = self.human
        return self.client.post(f'/api/storage/{key}/clear', json={'conv_id': 'root'})

    def listing(self):
        self.actor = self.human
        return {item['key']: item for item in self.client.get('/api/storage').json()}

    def test_session_homes_only_unused_unresumable_ones_are_cleared(self):
        self.att('running', status='running', cli_session='s1')
        self.att('resumable', cli_session='s2')
        self.att('fresh')
        self.att('planned')
        self.plan(['planned'])
        sizes = (('running', 10), ('resumable', 20), ('fresh', 300), ('planned', 40), ('orphan', 5000))
        for name, size in sizes:
            self.fill(os.path.join(self.sessions, 'codex', name), size)
        self.fill(os.path.join(self.sessions, 'fence', 'mirror'), 7)
        listed = self.listing()['sessions']
        self.assertEqual((listed['clearable_count'], listed['clearable_bytes']), (2, 5300))
        self.assertEqual(listed['bytes'], 10 + 20 + 300 + 40 + 5000 + 7)
        done = self.clear('sessions').json()
        self.assertEqual(done['freed_bytes'], 5300)
        self.assertEqual(sorted(os.path.basename(p) for p in done['removed']), ['fresh', 'orphan'])
        self.assertEqual(sorted(os.listdir(os.path.join(self.sessions, 'codex'))),
                         ['planned', 'resumable', 'running'])
        self.assertTrue(os.path.isdir(os.path.join(self.sessions, 'fence', 'mirror')))
        reasons = {os.path.basename(item['path']): item['reason'] for item in done['skipped']}
        self.assertIn('restart plan', reasons['planned'])
        notices = [m['body'] for m in self.db.list_messages('root') if 'storage cleared' in m['body']]
        self.assertEqual(len(notices), 1)
        self.assertIn('@human: CLI session homes', notices[0])

    def test_temporary_files_of_running_or_planned_processes_are_kept(self):
        self.att('live', status='running')
        self.att('idle')
        self.att('planned')
        self.plan(['planned'])
        base = attachment_tmp.base_dir()
        for name, size in (('live', 11), ('idle', 222), ('planned', 33)):
            self.fill(base / name, size)
        done = self.clear('tmp').json()
        self.assertEqual(done['freed_bytes'], 222)
        self.assertEqual(sorted(os.listdir(base)), ['live', 'planned'])

    def make_worktree(self, folder, name, base='main'):
        path = os.path.join(self.repo, folder, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        git(self.repo, 'worktree', 'add', '--detach', path, base)
        return path

    async def test_review_checkouts_in_use_are_kept(self):
        await self.create()
        line = self.db.get_conversation(self.conv_id)['cwd']
        with open(os.path.join(line, 'f.txt'), 'w') as handle:
            handle.write('x')
        git(line, 'add', 'f.txt')
        git(line, 'commit', '-q', '-m', 'f')
        row = await request_review(self.runtime, self.worker, self.conv_id,
                                   ReviewRequestIn(sha=git(line, 'rev-parse', 'HEAD'), what='w', where='x'))
        reviewing = row['review_worktree']
        idle = self.make_worktree('.review', 'a' * 40)
        busy = self.make_worktree('.review', 'b' * 40)
        self.att('worker2', status='running', cwd=busy)
        self.fill(idle, 100)
        before = self.listing()['review']
        self.assertEqual(before['clearable_count'], 1)
        done = self.clear('review').json()
        self.assertEqual(done['removed'], [idle])
        self.assertTrue(done['freed_bytes'] >= 100)
        self.assertTrue(os.path.isdir(reviewing) and os.path.isdir(busy))
        self.assertNotIn(idle, git(self.repo, 'worktree', 'list'))

    def test_scratch_worktrees_need_merged_clean_and_unused(self):
        merged = self.make_worktree('.scratch', 'm' * 40)
        dirty = self.make_worktree('.scratch', 'd' * 40)
        with open(os.path.join(dirty, 'new.txt'), 'w') as handle:
            handle.write('uncommitted')
        ahead = self.make_worktree('.scratch', 'a' * 40)
        git(ahead, 'commit', '--allow-empty', '-q', '-m', 'unmerged work')
        busy = self.make_worktree('.scratch', 'c' * 40)
        self.att('digger', status='running', cwd=busy)
        done = self.clear('scratch').json()
        self.assertEqual(done['removed'], [merged])
        for kept in (dirty, ahead, busy):
            self.assertTrue(os.path.isdir(kept), kept)
        reasons = ' '.join(item['reason'] for item in done['skipped'])
        for phrase in ('uncommitted', 'not merged', 'running process'):
            self.assertIn(phrase, reasons)

    def test_processes_cannot_inspect_or_clear_and_fixed_categories_are_not_clearable(self):
        for actor in (self.captain, self.worker if hasattr(self, 'worker') else self.captain):
            self.actor = actor
            self.assertEqual(self.client.get('/api/storage').status_code, 403)
            self.assertEqual(self.client.post('/api/storage/tmp/clear').status_code, 403)
        self.actor = self.human
        for key in ('media', 'database', 'nothing'):
            self.assertEqual(self.client.post(f'/api/storage/{key}/clear').status_code, 404)
        listed = self.listing()
        self.assertEqual(listed['media']['bytes'], 321)
        self.assertFalse(listed['media']['clearable'])
        self.assertGreater(listed['database']['bytes'], 0)
        self.assertEqual({'sessions', 'tmp', 'review', 'scratch', 'media', 'database'}, set(listed))

    def test_a_listing_creates_nothing_and_a_short_budget_marks_sizes_approximate(self):
        self.listing()
        self.assertFalse(os.path.exists(os.path.join(self.repo, '.review')))
        self.assertFalse(os.path.exists(self.sessions))
        self.fill(os.path.join(self.sessions, 'codex', 'gone'), 100)
        with patch.object(storage_survey, 'BUDGET_SECONDS', 0.0):
            self.assertTrue(self.listing()['sessions']['approximate'])
