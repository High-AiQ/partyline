"""Real short-lived jobs protect temp files before and after captain detach."""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from partyline.attachment_tmp import attachment_tmp_dir, base_dir, ensure_tmp_dir, reap_tmp_dir
from partyline.captain_handover import accept, offer, state_text
from partyline.captain_handover_completion import confirm, finish_detach, maintenance_once
from partyline.db import Db
from partyline.hierarchy import set_lead
from partyline.hierarchy_routes import hierarchy_router
from partyline.tmp_processes import in_use, references


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux process inventory')
class LiveJobsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {'PARTYLINE_TMP_BASE': self.tmp.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.db = Db(self.tmp.name + '/test.db')
        self.addCleanup(self.db.close)
        self.db.create_conversation('line', 'test')
        for name in ('old', 'new'):
            self.db.add_attachment(name, 'line', name, 'fake', [], self.tmp.name)
            self.db.set_attachment_status(name, 'running', None)
        self.db._exec('UPDATE attachments SET created_at=?', (time.time() - 100,))
        set_lead(self.db, 'line', 'old')
        self.ident, _ = offer(self.db, 'line', 'old', 'new', 'files', {'old', 'new'})
        accept(self.db, 'line', 'new', self.ident, {'old', 'new'})
        self.path = Path(ensure_tmp_dir({'id': 'old'}))
        self.file = self.path / 'log'
        self.file.write_text('preserved')
        self.runtime = SimpleNamespace(db=self.db, live={}, resume_locks={},
                                       broadcast=AsyncMock(), route_mentions=AsyncMock())

    def spawn(self, *, fd=False):
        if fd:
            output = open(self.file, 'a')
            try:
                proc = subprocess.Popen(['sleep', '30'], stdout=output, cwd=self.tmp.name)
            finally:
                output.close()
        else:
            proc = subprocess.Popen(['sleep', '30'], cwd=self.path)
        def stop():
            if proc.poll() is None:
                proc.kill()
            proc.wait()
        self.addCleanup(stop)
        return proc

    def isolated_inventory(self, proc):
        # /proc of unrelated sessions can be inaccessible under a write fence.
        # Supply the real test child only, keeping actual cwd/fd inspection.
        original = Path.iterdir
        return patch.object(Path, 'iterdir', lambda path:
            iter([Path(f'/proc/{proc.pid}')]) if str(path) == '/proc' else original(path))

    def test_reap_waits_for_cwd_then_maintenance_reaps_after_exit(self):
        proc = self.spawn()
        with self.isolated_inventory(proc):
            self.assertTrue(in_use(self.path))
            self.assertIsNone(reap_tmp_dir('old'))
            self.assertTrue(self.file.exists())
            manifest = base_dir() / '.pending-reaps/old.json'
            self.assertTrue(manifest.exists())
            proc.terminate()
            proc.wait()
            asyncio.run(maintenance_once(self.runtime))
            self.assertFalse(self.path.exists())
            self.assertFalse(manifest.exists())

    def test_reap_waits_for_open_fd_without_cwd(self):
        proc = self.spawn(fd=True)
        with self.isolated_inventory(proc):
            cwd, files, certain = references(proc.pid, self.path)
            self.assertNotEqual(cwd, str(self.path))
            self.assertEqual(files, [str(self.file)])
            self.assertTrue(certain)
            self.assertIsNone(reap_tmp_dir('old'))
            proc.terminate()
            proc.wait()
            self.assertEqual(reap_tmp_dir('old'), len('preserved'))

    def test_http_guard_transfer_notice_and_retained_read_write(self):
        proc = self.spawn()
        # The test process stands in for the old CLI; its real sleep child is
        # the job. Restrict the snapshot to that pair to exclude test tooling.
        self.runtime.live['old'] = SimpleNamespace(proc=SimpleNamespace(pid=os.getpid()))
        snapshot = ({os.getpid(): 1, proc.pid: os.getpid()}, {proc.pid: 1})
        app = FastAPI()
        app.include_router(hierarchy_router(self.runtime))
        actor = SimpleNamespace(kind='machine', conv_id='line', attachment_id='old')
        with patch('partyline.handover_jobs.process_snapshot', return_value=snapshot), \
             patch('partyline.captain_handover.request_principal', return_value=actor), \
             patch('partyline.captain_handover_completion._try_detach', new_callable=AsyncMock), \
             TestClient(app) as client:
            from partyline.handover_job_cache import refresh
            asyncio.run(refresh(self.runtime, 'old'))
            self.assertIn(str(proc.pid), state_text(self.db, 'new', self.runtime))
            response = client.post('/api/conversations/line/handover/complete',
                                   json={'handover_id': self.ident})
            self.assertEqual(response.status_code, 409, response.text)
            for value in (str(proc.pid), 'sleep', str(self.path), 'live_jobs'):
                self.assertIn(value, response.json()['detail'])
            self.assertEqual(self.db._exec('SELECT from_done FROM captain_handovers').fetchone()[0], 0)
            for caller in ('old', 'new'):
                actor.attachment_id = caller
                response = client.post('/api/conversations/line/handover/complete',
                    json={'handover_id': self.ident, 'live_jobs': 'transfer'})
                self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['state'], 'completed')
            notice = self.db.list_messages('line')[-1]['body']
            self.assertIn(str(proc.pid), notice)
            self.assertIn(str(self.path), notice)
            self.assertIn('retained', notice)
            delivered = self.runtime.route_mentions.await_args.args[1]
            self.assertEqual(delivered['audience_attachment_id'], 'new')
            self.assertIn(str(proc.pid), delivered['body'])
            manifest = base_dir() / '.pending-reaps/old.json'
            self.assertEqual(json.loads(manifest.read_text())['conv_id'], 'line')
            link = attachment_tmp_dir('new') / 'retained/old'
            self.assertEqual((link / 'log').read_text(), 'preserved')
            (link / 'log').write_text('successor wrote')
            self.assertEqual(self.file.read_text(), 'successor wrote')
            async def detach(runtime, att_id):
                runtime.live.pop(att_id)
                self.db.set_attachment_status(att_id, 'detached', None)
            row = dict(self.db._exec('SELECT * FROM captain_handovers').fetchone())
            with self.isolated_inventory(proc), \
                 patch('partyline.captain_handover_completion.detach_attachment', side_effect=detach):
                asyncio.run(finish_detach(self.runtime, row))
                self.assertIsNone(self.db.get_attachment('old'))
                self.assertTrue(self.file.exists())
                proc.terminate()
                proc.wait()
                # Pending records survive attachment removal and DB reopen.
                self.db.close()
                self.db = Db(self.tmp.name + '/test.db')
                self.addCleanup(self.db.close)
                self.runtime.db = self.db
                asyncio.run(maintenance_once(self.runtime))
                self.assertFalse(self.path.exists())

    def test_unauthorized_confirm_cannot_inspect_jobs(self):
        with patch('partyline.handover_jobs.live_jobs') as inventory:
            with self.assertRaises(HTTPException):
                confirm(self.db, 'line', 'outsider', self.ident)
            inventory.assert_not_called()

    def test_unknown_inspection_retains_directory(self):
        with patch('partyline.tmp_processes.sys.platform', 'darwin'):
            self.assertIsNone(reap_tmp_dir('old'))
        from partyline.tmp_owners import record
        proc = self.spawn()
        record('old', SimpleNamespace(proc=proc))
        with patch('partyline.tmp_processes.references', return_value=('?', [], False)), \
             self.isolated_inventory(proc):
            self.assertIsNone(reap_tmp_dir('old'))
        self.assertTrue(self.file.exists())

    def test_a_new_job_after_first_confirmation_is_checked_again(self):
        confirm(self.db, 'line', 'old', self.ident)
        proc = self.spawn()
        self.runtime.live['old'] = SimpleNamespace(proc=SimpleNamespace(pid=os.getpid()))
        with patch('partyline.handover_jobs.process_snapshot',
                   return_value=({proc.pid: os.getpid()}, {proc.pid: 1})):
            with self.assertRaises(HTTPException) as caught:
                from partyline.handover_jobs import live_jobs
                jobs = live_jobs(self.runtime, 'old')
                confirm(self.db, 'line', 'new', self.ident, jobs=jobs)
            self.assertEqual(caught.exception.status_code, 409)
        row = self.db._exec('SELECT * FROM captain_handovers').fetchone()
        self.assertEqual((row['state'], row['from_done'], row['to_done']), ('accepted', 1, 0))

    def test_scope_and_fence_launchers_and_cli_are_not_jobs(self):
        from partyline.handover_jobs import _cli_processes
        parents = {2: 1, 3: 2, 4: 3, 5: 4}
        arguments = {1: ['bwrap'], 2: ['bwrap'], 3: ['node', '/bin/codex.js'],
                     4: ['/vendor/codex'], 5: ['sleep', '30']}
        with patch('partyline.handover_jobs.argv', side_effect=arguments.get):
            self.assertEqual(_cli_processes(parents, 1,
                SimpleNamespace(att={'command': ['codex']})), {1, 2, 3, 4})

    def test_tracked_transfer_waits_even_without_a_live_cwd_or_fd(self):
        from partyline.tmp_retention import remember
        proc = subprocess.Popen(['sleep', '30'], cwd=self.tmp.name)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        remember('old', 'line', 'new', [{'host_pid': proc.pid}])
        with self.isolated_inventory(proc):
            self.assertIsNone(reap_tmp_dir('old'))
            proc.terminate()
            proc.wait()
            asyncio.run(maintenance_once(self.runtime))
            self.assertFalse(self.path.exists())

    def test_missing_process_snapshot_refuses_completion(self):
        self.runtime.live['old'] = SimpleNamespace(proc=SimpleNamespace(pid=os.getpid()))
        from partyline.captain_handover import CompleteIn
        from partyline.captain_handover_completion import complete_route
        actor = SimpleNamespace(kind='machine', conv_id='line', attachment_id='new')
        with patch('partyline.handover_jobs.process_snapshot', return_value=None), \
             patch('partyline.captain_handover.request_principal', return_value=actor):
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(complete_route(self.runtime, None, 'line', CompleteIn(handover_id=self.ident)))
            self.assertEqual(caught.exception.status_code, 409)

    def test_retention_survives_windows_without_symlink_privilege(self):
        from partyline.tmp_retention import remember
        with patch('partyline.tmp_retention.sys', SimpleNamespace(platform='win32')), \
             patch.object(Path, 'symlink_to', side_effect=OSError('privilege unavailable')):
            self.assertEqual(remember('old', 'line', 'new'), self.path)
        self.assertEqual(self.file.read_text(), 'preserved')
        manifest = base_dir() / '.pending-reaps/old.json'
        self.assertEqual(json.loads(manifest.read_text())['conv_id'], 'line')

    def test_another_cli_started_by_the_cli_remains_a_job(self):
        from partyline.handover_jobs import _cli_processes
        with patch('partyline.handover_jobs.argv', side_effect=lambda pid: ['codex']):
            self.assertEqual(_cli_processes({2: 1}, 1,
                SimpleNamespace(att={'command': ['codex']})), {1})
