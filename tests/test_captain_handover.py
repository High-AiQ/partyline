"""Durable handover offer and acceptance."""
import sqlite3
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace

from fastapi import HTTPException

from partyline.captain_handover import OFFER_TTL_SECONDS, accept, cancel, offer, state_text
from partyline.db import Db
from partyline.hierarchy import set_lead


class HandoverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = self.tmp.name + '/db'
        self.db = Db(self.path)
        for conv in ('line', 'other'):
            self.db.create_conversation(conv, conv)
        for name, conv in (('old', 'line'), ('new', 'line'), ('third', 'line'), ('foreign', 'other')):
            self.db.add_attachment(name, conv, name, 'fake', [], '/tmp')
            self.db.set_attachment_status(name, 'running', None)
        self.now = time.time()
        self.db._exec('UPDATE attachments SET created_at=?', (self.now - 100,))
        set_lead(self.db, 'line', 'old')
        self.live = {'old', 'new', 'third', 'foreign'}

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def offer(self, target='new', debrief='See notes/worktree', old='old', **kwargs):
        return offer(self.db, 'line', old, target, debrief, self.live, now=self.now, **kwargs)

    def accept(self, ident, caller='new', **kwargs):
        return accept(self.db, 'line', caller, ident, self.live, now=self.now, **kwargs)

    def test_success_and_restart_persistence(self):
        self.db._exec('INSERT INTO line_bridges VALUES(?,?,?,?,?,?,?,?,?,?)',
                      ('b', 'line', 'old', 'other', 'foreign', 1, 'human', None, None, None))
        self.db._exec("INSERT INTO conversation_write_grant_requests VALUES('line','r','/x','old','old',1)")
        ident, message = self.offer()
        self.assertIn('handover offer', message['body'])
        self.assertEqual(message['audience_attachment_id'], 'new')
        self.assertTrue(self.db.get_attachment('old')['is_lead'])
        self.db.close()
        self.db = Db(self.path)
        old, target, message = self.accept(ident)
        self.assertEqual((old['name'], target['name']), ('old', 'new'))
        self.assertIn('handed captainship', message['body'])
        self.assertFalse(self.db.get_attachment('old')['is_lead'])
        self.assertTrue(self.db.get_attachment('new')['is_lead'])
        self.assertEqual(self.db._exec('SELECT a_attachment_id FROM line_bridges').fetchone()[0], 'new')
        self.assertEqual(self.db._exec('SELECT requester_attachment_id FROM '
                                       'conversation_write_grant_requests').fetchone()[0], 'new')
        self.assertIn('handing off', state_text(self.db, 'old'))
        self.assertIn('accepted', state_text(self.db, 'new'))
        self.assertEqual(self.db.get_attachment('old')['status'], 'running')

    def test_rejections(self):
        for kwargs, expected in [({'old': 'third'}, 'current live captain'),
                                 ({'target': 'old'}, 'yourself'), ({'target': 'foreign'}, 'same line'),
                                 ({'target': 'missing'}, 'same line'), ({'debrief': ' '}, 'required'),
                                 ({'debrief': 'x' * 4001}, '4001'),
                                 ({'pending': SimpleNamespace(requester_attachment_id='old')},
                                  'pending restart')]:
            with self.subTest(kwargs=kwargs), self.assertRaises(HTTPException) as caught:
                self.offer(**kwargs)
            self.assertIn(expected, caught.exception.detail)
        self.db.set_attachment_status('new', 'detached', None)
        with self.assertRaises(HTTPException):
            self.offer()
        self.db.set_attachment_status('new', 'running', None)
        self.db._exec("UPDATE attachments SET created_at=? WHERE id='new'", (self.now - 10,))
        with self.assertRaises(HTTPException) as caught:
            self.offer()
        self.assertIn('50 seconds remain', caught.exception.detail)
        self.db._exec("UPDATE attachments SET created_at=? WHERE id='new'", (self.now - 100,))
        ident, _ = self.offer()
        with self.assertRaises(HTTPException):
            self.offer(target='third')
        with self.assertRaises(HTTPException):
            self.accept(ident, caller='third')
        with self.assertRaises(HTTPException):
            self.accept(ident, pending=SimpleNamespace(requester_attachment_id='old'))

    def test_cancel_and_expiry(self):
        ident, _ = self.offer()
        with self.assertRaises(HTTPException):
            cancel(self.db, 'line', 'new', ident, now=self.now)
        cancel(self.db, 'line', 'old', ident, now=self.now)
        with self.assertRaises(HTTPException):
            self.accept(ident)
        ident, _ = self.offer()
        with self.assertRaises(HTTPException):
            accept(self.db, 'line', 'new', ident, self.live, now=self.now + OFFER_TTL_SECONDS)
        self.assertEqual(self.db._exec('SELECT state FROM captain_handovers WHERE id=?', (ident,))
                         .fetchone()[0], 'expired')
        offer(self.db, 'line', 'old', 'new', 'notes', self.live, now=self.now + OFFER_TTL_SECONDS)

    def test_failure_rolls_back_accept(self):
        self.db._exec('INSERT INTO line_bridges VALUES(?,?,?,?,?,?,?,?,?,?)',
                      ('b', 'line', 'old', 'other', 'foreign', 1, 'human', None, None, None))
        ident, _ = self.offer()
        self.db._exec("CREATE TRIGGER fail_handover BEFORE UPDATE OF a_attachment_id ON line_bridges "
                      "BEGIN SELECT RAISE(ABORT, 'simulated'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.accept(ident)
        self.assertTrue(self.db.get_attachment('old')['is_lead'])
        self.assertFalse(self.db.get_attachment('new')['is_lead'])
        self.assertEqual(self.db._exec('SELECT state FROM captain_handovers').fetchone()[0], 'offered')
        self.assertEqual(self.db._exec('SELECT a_attachment_id FROM line_bridges').fetchone()[0], 'old')

    def test_race_offers(self):
        outcomes = []
        barrier = threading.Barrier(2)
        def run(target):
            barrier.wait()
            try:
                self.offer(target=target)
                outcomes.append('ok')
            except HTTPException:
                outcomes.append('rejected')
        threads = [threading.Thread(target=run, args=(name,)) for name in ('new', 'third')]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertCountEqual(outcomes, ['ok', 'rejected'])

    def test_routes_offer_and_accept(self):
        from unittest.mock import AsyncMock, patch
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from partyline.hierarchy_routes import hierarchy_router

        runtime = SimpleNamespace(db=self.db, live={name: object() for name in self.live}, resume_locks={},
                                  route_mentions=AsyncMock(), broadcast=AsyncMock(),
                                  activation_matches=lambda adapter, att: True)
        app = FastAPI()
        app.include_router(hierarchy_router(runtime))
        old = SimpleNamespace(kind='machine', conv_id='line', attachment_id='old', name='old')
        new = SimpleNamespace(kind='machine', conv_id='line', attachment_id='new', name='new')
        with patch('partyline.captain_handover.request_principal', side_effect=[old, new]), \
             patch('partyline.captain_handover.post_private', new_callable=AsyncMock,
                   return_value={'body': '', 'audience_attachment_id': 'new'}), \
             patch('partyline.captain_handover.ring_workers', new_callable=AsyncMock), \
             TestClient(app) as client:
            response = client.post('/api/conversations/line/handover/offer',
                                   json={'attachment_id': 'new', 'debrief': 'See notes'})
            self.assertEqual(response.status_code, 200, response.text)
            ident = response.json()['handover_id']
            response = client.post('/api/conversations/line/handover/accept', json={'handover_id': ident})
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['state'], 'accepted')
        self.assertEqual(runtime.route_mentions.await_args_list[0].args[1]['body'], '')
        self.assertTrue(self.db.get_attachment('new')['is_lead'])

    def test_mcp_tools_available_to_receiver(self):
        from partyline.mcp import tools_handover
        state = {'kind': 'machine', 'role': 'worker'}
        self.assertEqual({t['name'] for t in tools_handover.tool_list(state)},
                         {'offer_handover', 'accept_handover', 'cancel_handover', 'complete_handover'})
        with self.assertRaisesRegex(ValueError, '4001'):
            tools_handover.call(None, 'offer_handover',
                                {'attachment_id': 'new', 'debrief': 'x' * 4001}, state)

    def test_accept_racing_detach_keeps_one_captain(self):
        ident, _ = self.offer()
        barrier = threading.Barrier(2)
        outcomes = []
        def move():
            barrier.wait()
            try:
                self.accept(ident)
                outcomes.append('accepted')
            except HTTPException:
                outcomes.append('rejected')
        def detach():
            barrier.wait()
            self.db.set_attachment_status('new', 'detached', None)
        threads = [threading.Thread(target=fn) for fn in (move, detach)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertIn(outcomes[0], ('accepted', 'rejected'))
        self.assertEqual(self.db._exec('SELECT COUNT(*) FROM attachments WHERE is_lead=1').fetchone()[0], 1)
        if outcomes[0] == 'rejected':
            self.assertTrue(self.db.get_attachment('old')['is_lead'])

    def test_archived_and_cancelled_offers_are_refused(self):
        self.db._exec("UPDATE conversations SET archived_at=? WHERE id='line'", (self.now,))
        with self.assertRaisesRegex(HTTPException, 'archived'):
            self.offer()
        self.db._exec("UPDATE conversations SET archived_at=NULL WHERE id='line'")
        ident, _ = self.offer()
        cancel(self.db, 'line', 'old', ident, now=self.now)
        with self.assertRaisesRegex(HTTPException, 'not an active offer'):
            cancel(self.db, 'line', 'old', ident, now=self.now)

    def test_detach_and_accept_both_orders(self):
        import asyncio
        from partyline.captain_handover import _locks

        async def scenario(detach_first):
            ident, _ = self.offer()
            runtime = SimpleNamespace(db=self.db, resume_locks={})
            target_lock = runtime.resume_locks.setdefault('new', asyncio.Lock())
            entered = asyncio.Event()
            release = asyncio.Event()
            async def detach():
                async with target_lock:
                    entered.set()
                    await release.wait()
                    self.db.set_attachment_status('new', 'detached', None)
            if detach_first:
                task = asyncio.create_task(detach())
                await entered.wait()
                accepting = asyncio.create_task(_locks(runtime, ['old', 'new'], lambda: self.accept(ident)))
                await asyncio.sleep(0)
                self.assertFalse(accepting.done())
                release.set()
                await task
                with self.assertRaises(HTTPException):
                    await accepting
                self.assertTrue(self.db.get_attachment('old')['is_lead'])
            else:
                accepted = await _locks(runtime, ['old', 'new'], lambda: self.accept(ident))
                self.assertEqual(accepted[1]['id'], 'new')
                release.set()
                await detach()
                self.assertTrue(self.db.get_attachment('new')['is_lead'])
                self.assertEqual(self.db.get_attachment('new')['status'], 'detached')
        asyncio.run(scenario(True))
        self.db._exec("UPDATE captain_handovers SET state='cancelled' WHERE state='offered'")
        self.db.set_attachment_status('new', 'running', None)
        asyncio.run(scenario(False))

    def test_missing_branches_and_mcp_dispatch(self):
        from unittest.mock import patch
        from partyline.captain_handover import _live_ids, _principal
        from partyline.mcp import tools_handover

        with patch('partyline.captain_handover.request_principal',
                   return_value=SimpleNamespace(kind='user', conv_id='line')):
            with self.assertRaises(HTTPException):
                _principal(None, 'line')
        runtime = SimpleNamespace(db=self.db, live={'old': object()}, activation_matches=lambda a, b: False)
        self.assertEqual(_live_ids(runtime, ['old', 'missing']), set())
        state = {'kind': 'machine'}
        client = SimpleNamespace(home='line', request=lambda *args: args)
        with self.assertRaisesRegex(ValueError, 'debrief is required'):
            tools_handover.call(client, 'offer_handover', {'attachment_id': 'new', 'debrief': ''}, state)
        self.assertEqual(tools_handover.call(client, 'accept_handover', {'handover_id': 'id'}, state),
                         ('POST', '/api/conversations/line/handover/accept', {'handover_id': 'id'}))

    def test_cancel_route(self):
        from unittest.mock import patch
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from partyline.hierarchy_routes import hierarchy_router

        ident, _ = self.offer()
        runtime = SimpleNamespace(db=self.db, live={}, resume_locks={})
        app = FastAPI()
        app.include_router(hierarchy_router(runtime))
        actor = SimpleNamespace(kind='machine', conv_id='line', attachment_id='old', name='old')
        with patch('partyline.captain_handover.request_principal', return_value=actor), \
             TestClient(app) as client:
            response = client.post('/api/conversations/line/handover/cancel', json={'handover_id': ident})
        self.assertEqual(response.json()['state'], 'cancelled')
