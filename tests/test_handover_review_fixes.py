"""MCP helpers, nonblocking inventory, and ownership-scoped cleanup uncertainty."""
import asyncio
import json
import os
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from partyline.attachment_tmp import reap_tmp_dir
from partyline.captain_handover import CompleteIn, state_text
from partyline.captain_handover_completion import complete_route
from partyline.handover_job_cache import refresh
from partyline.handover_mcp import commands, matches
from partyline.tmp_owners import owned, record
from tests import test_handover_live_jobs as base


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux process inventory')
class ReviewFixesTest(unittest.TestCase):
    setUp = base.LiveJobsTest.setUp
    spawn = base.LiveJobsTest.spawn
    isolated_inventory = base.LiveJobsTest.isolated_inventory

    def test_configured_mcp_child_needs_no_transfer_for_claude_or_codex(self):
        from partyline.hierarchy_routes import hierarchy_router
        server_args = ['-c', 'import time; time.sleep(30)']
        proc = subprocess.Popen([sys.executable, *server_args], cwd=self.tmp.name)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        command = sys.executable
        config = Path(self.tmp.name) / 'mcp.json'
        config.write_text(json.dumps({'mcpServers': {
            'partyline': {'command': command, 'args': server_args}}}))
        actor = SimpleNamespace(kind='machine', conv_id='line', attachment_id='old')
        app = FastAPI()
        app.include_router(hierarchy_router(self.runtime))
        snapshot = ({proc.pid: os.getpid()}, {})
        for cli in ('claude', 'codex'):
            with self.subTest(cli=cli):
                self.db._exec("UPDATE captain_handovers SET state='accepted',from_done=0,to_done=0,"
                              "completed_at=NULL WHERE id=?", (self.ident,))
                adapter = SimpleNamespace(proc=SimpleNamespace(pid=os.getpid()), att={'command': [cli]})
                if cli == 'claude':
                    adapter.att['mcp_config'] = str(config)
                    adapter.spawn_argv = [cli, '--mcp-config', str(config)]
                else:
                    adapter.spawn_argv = [cli, '-c', f'mcp_servers.partyline.command={json.dumps(command)}',
                                          '-c', f'mcp_servers.partyline.args={json.dumps(server_args)}']
                self.runtime.live['old'] = adapter
                with patch('partyline.handover_jobs.process_snapshot', return_value=snapshot), \
                     patch('partyline.captain_handover.request_principal', return_value=actor), \
                     patch('partyline.captain_handover_completion._try_detach', new_callable=AsyncMock), \
                     TestClient(app) as client:
                    for caller in ('old', 'new'):
                        actor.attachment_id = caller
                        response = client.post('/api/conversations/line/handover/complete',
                                               json={'handover_id': self.ident})
                        self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json()['state'], 'completed')

    def test_inventory_runs_off_loop_before_database_transaction_or_lock(self):
        started, release = threading.Event(), threading.Event()
        def inspect(runtime, att_id):
            self.assertFalse(self.db.conn.in_transaction)
            acquired = self.db.lock.acquire(blocking=False)
            self.assertTrue(acquired)
            if acquired:
                self.db.lock.release()
            with self.assertRaises(RuntimeError):
                asyncio.get_running_loop()
            started.set()
            self.assertTrue(release.wait(2))
            return []
        actor = SimpleNamespace(kind='machine', conv_id='line', attachment_id='old')
        async def scenario():
            task = asyncio.create_task(complete_route(self.runtime, None, 'line',
                                                     CompleteIn(handover_id=self.ident)))
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 2))
                self.assertFalse(task.done())  # event loop is free while inventory waits
            finally:
                release.set()
            self.assertEqual((await task)['state'], 'accepted')
        with patch('partyline.handover_jobs.inspect_completion', side_effect=inspect), \
             patch('partyline.captain_handover.request_principal', return_value=actor):
            asyncio.run(scenario())

    def test_rider_uses_cache_and_inventory_errors_never_raise(self):
        self.runtime.live['old'] = SimpleNamespace(proc=SimpleNamespace(pid=os.getpid()))
        with patch('partyline.handover_job_cache.live_jobs',
                   side_effect=HTTPException(409, 'inspection unavailable')) as inspect:
            asyncio.run(refresh(self.runtime, 'old'))
            self.assertIn('inventory unavailable', state_text(self.db, 'new', self.runtime))
            self.assertIn('inventory unavailable', state_text(self.db, 'new', self.runtime))
            self.assertEqual(inspect.call_count, 1)
        entry = self.runtime.handover_job_cache['old']
        entry['at'] = 0
        with patch('partyline.handover_job_cache._executor') as executor:
            self.assertIn('refreshing', state_text(self.db, 'new', self.runtime))
            state_text(self.db, 'new', self.runtime)
            self.assertEqual(executor.submit.call_count, 1)

    def test_denied_foreign_pid_does_not_pin_directory(self):
        proc = subprocess.Popen(['sleep', '30'], cwd=self.tmp.name)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        with self.isolated_inventory(proc), \
             patch('partyline.tmp_processes.references', return_value=('?', [], False)):
            self.assertEqual(reap_tmp_dir('old'), len('preserved'))
        self.assertFalse(self.path.exists())

    def test_denied_owned_pid_protects_directory_until_it_exits(self):
        proc = self.spawn()
        record('old', SimpleNamespace(proc=proc))
        self.assertIn(proc.pid, owned('old'))
        with self.isolated_inventory(proc), \
             patch('partyline.tmp_processes.references', return_value=('?', [], False)):
            self.assertIsNone(reap_tmp_dir('old'))
            proc.terminate()
            proc.wait()
            self.assertEqual(reap_tmp_dir('old'), len('preserved'))

    def test_mcp_command_match_is_exact_and_codex_home_is_merged(self):
        home = Path(self.tmp.name) / 'codex'
        home.mkdir()
        (home / 'config.toml').write_text('[mcp_servers.helper]\ncommand="sleep"\nargs=["30"]\n')
        adapter = SimpleNamespace(_home=str(home), att={}, spawn_argv=[
            'codex', '-c', 'mcp_servers.helper.args=["31"]'])
        configured = commands(adapter)
        self.assertTrue(matches(['/bin/sleep', '31'], configured))
        self.assertFalse(matches(['/bin/sleep', '31', '--extra'], configured))
        self.assertFalse(matches(['/bin/sleep', '30'], configured))

    def test_saved_scope_finds_reparented_process_after_root_exits(self):
        from partyline.tmp_owners import _path
        proc = self.spawn()
        scope = Path(self.tmp.name) / 'scope'
        scope.mkdir()
        (scope / 'cgroup.procs').write_text(str(proc.pid))
        path = _path('old')
        path.parent.mkdir()
        path.write_text(json.dumps({'root': 999999999, 'processes': {}, 'scope': str(scope)}))
        self.assertIn(proc.pid, owned('old'))

    def test_async_close_reaps_in_worker_thread(self):
        from partyline.line_process_routes import close_attachment
        def reap(att_id):
            with self.assertRaises(RuntimeError):
                asyncio.get_running_loop()
            return 0
        with patch('partyline.line_process_routes.detach_attachment', new_callable=AsyncMock), \
             patch('partyline.line_process_routes.reap_tmp_dir', side_effect=reap) as cleanup:
            asyncio.run(close_attachment(self.runtime, 'old'))
        cleanup.assert_called_once_with('old')

    def test_bulk_stop_saves_ownership_before_stopping(self):
        from partyline.line_process_stop import stop_attachments
        proc = self.spawn()
        async def stop():
            self.assertIn(proc.pid, owned('old'))
        self.runtime.live['old'] = SimpleNamespace(proc=proc, att={}, stop=AsyncMock(side_effect=stop))
        self.assertEqual(asyncio.run(stop_attachments(self.runtime, 'line')), ['old'])
        self.assertNotIn('old', self.runtime.live)

    def test_a_later_activation_keeps_prior_scope_ownership(self):
        from partyline.tmp_owners import _path
        first = self.spawn()
        second = self.spawn()
        scopes = []
        for index, proc in enumerate((first, second)):
            scope = Path(self.tmp.name) / f'scope{index}'
            scope.mkdir()
            (scope / 'cgroup.procs').write_text(str(proc.pid))
            scopes.append(str(scope))
            with patch('partyline.tmp_owners.scope_path', return_value=scope):
                record('old', SimpleNamespace(proc=proc))
        payload = json.loads(_path('old').read_text())
        self.assertEqual(set(payload['scopes']), set(scopes))
        self.assertTrue({first.pid, second.pid}.issubset(owned('old')))

    def test_denied_saved_scope_protects_only_its_directory(self):
        from partyline.tmp_owners import _path
        path = _path('old')
        path.parent.mkdir()
        path.write_text(json.dumps({'roots': {}, 'processes': {}, 'scopes': ['/scope']}))
        with patch('partyline.tmp_owners.scope_inventory', return_value=(set(), False)):
            self.assertIsNone(reap_tmp_dir('old'))
        self.assertTrue(self.path.exists())

    def test_pending_reap_waits_for_an_active_attachment(self):
        from partyline.tmp_retention import remember, reap_pending
        remember('old')
        reap_pending({'old'})
        self.assertTrue(self.path.exists())
        reap_pending()
        self.assertFalse(self.path.exists())

    def test_jobs_started_below_an_mcp_server_still_count(self):
        from partyline.handover_jobs import live_jobs
        server_args = ['-c', 'import time; time.sleep(30)']
        server = subprocess.Popen([sys.executable, *server_args], cwd=self.tmp.name)
        self.addCleanup(server.wait)
        self.addCleanup(server.kill)
        job = self.spawn()
        config = Path(self.tmp.name) / 'mcp.json'
        config.write_text(json.dumps({'mcpServers': {
            'partyline': {'command': sys.executable, 'args': server_args}}}))
        self.runtime.live['old'] = SimpleNamespace(proc=SimpleNamespace(pid=os.getpid()),
            att={'command': ['claude'], 'mcp_config': str(config)})
        snapshot = ({server.pid: os.getpid(), job.pid: server.pid}, {})
        with patch('partyline.handover_jobs.process_snapshot', return_value=snapshot):
            self.assertEqual([item['host_pid'] for item in live_jobs(self.runtime, 'old')], [job.pid])
