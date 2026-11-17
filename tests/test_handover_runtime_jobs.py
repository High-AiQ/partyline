"""Handover inventories use process ancestry and server facts, never adapter names."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException

from partyline import handover_job_cache as cache, handover_jobs as jobs, handover_processes as processes
from partyline.captain_handover import CompleteIn, state_text
from partyline.captain_handover_completion import confirm
from partyline.mcp import catalog, tools_core
from partyline.mcp.client import PartylineClient
from tests import test_handover_complete_state as base


def fact(command='python worker.py', state='S', started='Tue Nov 17 12:00:00 2026'):
    return {'command': command, 'state': state, 'started': started, 'pgid': 20}


def job(pid=20, **extra):
    return {'pid': pid, 'host_pid': pid, 'command': 'python worker.py', 'state': 'S',
            'started': 'Tue Nov 17 12:00:00 2026', 'cwd': '/work', 'files': [], 'unknown': '', **extra}


class RuntimeInventoryTest(unittest.TestCase):
    def setUp(self):
        self.runtime = SimpleNamespace(live={'old': SimpleNamespace(proc=SimpleNamespace(pid=10))})

    def inventory(self, parents, facts, owned=(), scoped=None):
        with patch.object(jobs, 'process_snapshot', return_value=(parents, {})), \
             patch.object(jobs, 'members', return_value=set(parents) if scoped is None else set(scoped)), \
             patch.object(jobs, 'owned', return_value=set(owned)), \
             patch.object(jobs, 'listing', return_value=facts), \
             patch.object(jobs, 'describe', side_effect=lambda pid:
                          (facts.get(pid, {}).get('command'), '/work', '')), \
             patch.object(jobs, 'references', return_value=('/work', [], True)), \
             patch.object(jobs, 'namespace_pid', side_effect=lambda pid: pid):
            return jobs.live_jobs(self.runtime, 'old')

    def test_entire_attachment_tree_transfers_for_opencode_v2_claude_and_codex(self):
        for adapter in ('opencode-v2', 'claude', 'codex'):
            with self.subTest(adapter=adapter):
                self.runtime.live['old'].att = {'adapter': adapter, 'command': ['custom-launcher']}
                # Wrapper -> server -> MCP/daemon -> tool shell -> transient pipeline.
                parents = {10: 1, 11: 10, 12: 11, 13: 11, 14: 13, 15: 14, 16: 14}
                facts = {pid: fact(f'arbitrary-executable-{pid}') for pid in parents}
                self.assertEqual(self.inventory(parents, facts), [])
                # Fresh tool PIDs on the next wake do not change the blocking inventory.
                parents[25] = 14
                facts[25] = fact('another-unknown-wrapper')
                self.assertEqual(self.inventory(parents, facts), [])

    def test_only_live_owned_jobs_outside_the_tree_need_a_decision(self):
        parents = {10: 1, 11: 10, 20: 1, 21: 1, 22: 1, 23: 1, 24: 1}
        facts = {10: fact(), 11: fact(), 20: fact(), 21: fact('worker <defunct>', 'Z'),
                 22: fact(None), 23: fact('unknown'), 24: fact('worker', 'X'), 30: fact('unrelated worker')}
        result = self.inventory(parents, facts, owned={20, 21, 22, 23, 24, 99}, scoped={10, 11})
        self.assertEqual(result, [job()])

    def test_process_vanishing_after_the_listing_does_not_block(self):
        with patch.object(jobs, 'describe', return_value=(None, None, 'exited')):
            # Use direct patches so the vanishing process's describe result wins.
            with patch.object(jobs, 'process_snapshot', return_value=({10: 1}, {})), \
                 patch.object(jobs, 'members', return_value={10, 20}), \
                 patch.object(jobs, 'owned', return_value=set()), \
                 patch.object(jobs, 'listing', return_value={20: fact()}):
                self.assertEqual(jobs.live_jobs(self.runtime, 'old'), [])

    def test_missing_listing_facts_fall_back_to_per_pid_inspection_and_still_block(self):
        for facts in ({}, {21: fact()}):
            with self.subTest(facts=facts), \
                 patch.object(jobs, 'process_snapshot', return_value=({10: 1}, {})), \
                 patch.object(jobs, 'members', return_value={10}), \
                 patch.object(jobs, 'owned', return_value={20}), \
                 patch.object(jobs, 'listing', return_value=facts), \
                 patch.object(jobs, 'describe', return_value=('python worker.py', '/work', '')), \
                 patch.object(jobs, 'references', return_value=('/work', [], True)), \
                 patch.object(jobs, 'namespace_pid', side_effect=lambda pid: pid):
                self.assertEqual(jobs.live_jobs(self.runtime, 'old'),
                                 [job(state='unavailable', started='unavailable')])

    def test_linux_and_macos_batch_facts_include_state_command_and_birth_time(self):
        output = ('20 20 S Tue Nov 17 12:00:00 2026 python worker.py\n'
                  '21 20 Z Tue Nov 17 11:00:00 2026 worker <defunct>\n')
        for platform in ('linux', 'darwin'):
            with self.subTest(platform=platform), \
                 patch.object(processes.sys, 'platform', platform), \
                 patch.object(processes.subprocess, 'run', return_value=SimpleNamespace(
                     returncode=0, stdout=output)) as run:
                found = processes.listing()
                self.assertEqual(found[20], fact())
                self.assertFalse(processes.actionable(found[21]))
                self.assertIn('pid=,pgid=,stat=,lstart=,args=', run.call_args.args[0])
                self.assertEqual(run.call_args.kwargs['env']['LC_ALL'], 'C')

    def test_windows_birth_time_and_command_and_failed_listing(self):
        output = json.dumps({'ProcessId': 20, 'CreationDate': '2026-11-17T12:00:00Z',
                             'CommandLine': 'python worker.py'})
        with patch.object(processes.sys, 'platform', 'win32'), \
             patch.object(processes.subprocess, 'run', return_value=SimpleNamespace(
                 returncode=0, stdout=output)):
            value = processes.listing()[20]
            self.assertEqual(value['started'], '2026-11-17T12:00:00Z')
            self.assertTrue(processes.actionable(value))
        for result in (SimpleNamespace(returncode=1), SimpleNamespace(returncode=0, stdout='bad')):
            with patch.object(processes.subprocess, 'run', return_value=result):
                self.assertEqual(processes.listing(), {})


class RuntimeNoticeTest(unittest.TestCase):
    setUp = base.CompleteStateTest.setUp

    def test_both_confirmers_get_actionable_409_and_the_status_says_receiver_must_ack(self):
        for who in ('old', 'new'):
            with self.assertRaises(HTTPException) as caught:
                confirm(self.db, 'line', who, self.ident, jobs=[job()])
            self.assertEqual(caught.exception.status_code, 409)
            detail = caught.exception.detail
            for text in ('live_jobs', '"transfer"', 'Example:', 'receiver', 'state=S',
                         'started=Tue Nov 17 12:00:00 2026', 'python worker.py'):
                self.assertIn(text, detail)
        confirm(self.db, 'line', 'old', self.ident, jobs=[job()], live_jobs='transfer')
        status = state_text(self.db, 'new', self.runtime)
        self.assertIn('independently', status)
        self.assertIn('receiver', status)
        self.assertIn('each must pass live_jobs="transfer", including the receiver', status)
        self.assertIn('even after the old captain has acknowledged them', status)
        self.assertIn('"live_jobs": "transfer"', status)
        # The receiver's independent acknowledgment is intentional and documented.
        with self.assertRaises(HTTPException):
            confirm(self.db, 'line', 'new', self.ident, jobs=[job()])
        row, _ = confirm(self.db, 'line', 'new', self.ident, jobs=[job()], live_jobs='transfer')
        self.assertEqual(row['state'], 'completed')

    def test_large_list_truncates_at_whole_entries_and_survives_mcp(self):
        inventory = [job(pid) for pid in range(20, 60)]
        with self.assertRaises(HTTPException) as caught:
            confirm(self.db, 'line', 'old', self.ident, jobs=inventory)
        detail = caught.exception.detail
        shown = [line for line in detail.splitlines() if line.startswith('pid ')]
        self.assertIn(f'+{40 - len(shown)} more', detail)
        self.assertTrue(shown)
        self.assertTrue(all(line.endswith('tmp files=none observed') for line in shown))
        error = str(PartylineClient._error(409, json.dumps({'detail': detail}).encode()))
        self.assertIn(detail, error)
        self.assertLess(len(error), 3000)

    def test_many_long_files_keep_the_first_job_visible(self):
        inventory = [job(pid, files=['/work/' + 'x' * 3000 for _ in range(30)],
                         cwd='/work/' + 'x' * 3000) for pid in (20, 21)]
        text = jobs.jobs_text(inventory)
        self.assertIn('pid 20', text)
        self.assertIn('state=S', text)
        self.assertIn('started=Tue Nov 17 12:00:00 2026', text)
        self.assertIn('python worker.py', text)
        self.assertIn('+28 more files', text)
        self.assertLessEqual(len(text), 1800)

    def test_each_participant_sees_inventory_once_and_again_only_on_substantive_change(self):
        self.runtime.live['old'] = SimpleNamespace(proc=SimpleNamespace(pid=10))
        inventory = [job()]
        with patch.object(cache, 'live_jobs', side_effect=lambda *args: inventory), \
             patch.object(cache.time, 'monotonic', return_value=100):
            asyncio.run(cache.refresh(self.runtime, 'old'))
            for who in ('old', 'new'):
                self.assertIn('pid 20', state_text(self.db, who, self.runtime))
                self.assertIn('1 live jobs awaiting live_jobs decision; see first notice',
                              state_text(self.db, who, self.runtime))
            # State changes are noise; new process identities are substantive.
            inventory = [job(state='R')]
            asyncio.run(cache.refresh(self.runtime, 'old'))
            self.assertNotIn('pid 20', state_text(self.db, 'new', self.runtime))
            inventory = [job(started='Tue Nov 17 12:01:00 2026')]
            asyncio.run(cache.refresh(self.runtime, 'old'))
            self.assertIn('pid 20', state_text(self.db, 'new', self.runtime))
            # Another handover gets its own first notice.
            self.assertIn('pid 20', cache.state_jobs(self.runtime, 'old', 'next', 'new'))

    def test_complete_handover_guide_resolves_for_both_participant_roles(self):
        for state in ({'kind': 'machine', 'is_lead': True}, {'kind': 'machine', 'is_lead': False}):
            entry = tools_core.call(Mock(), 'guide', {'topic': 'complete_handover'}, state)
            self.assertEqual(entry['name'], 'complete_handover')
            self.assertIn('extras(', entry['call'])
            self.assertIn('receiver', entry['description'])
            allowed = entry['inputSchema']['properties']['live_jobs']['enum']
            self.assertEqual(allowed, ['transfer'])
            self.assertEqual(CompleteIn.model_fields['live_jobs'].annotation.__args__[0].__args__,
                             tuple(allowed))
            self.assertIn('complete_handover', {item['name'] for item in catalog.guide_index(state)['tools']})
