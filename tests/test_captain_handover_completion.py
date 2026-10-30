"""Two-party confirmation, timeout, and recovery of detach intent."""
import asyncio
import sqlite3
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from partyline.captain_handover import accept, offer, state_text
from partyline.captain_handover_completion import (
    CONFIRM_TIMEOUT_SECONDS, confirm, ensure_handover_detached, maintenance_once, pending_detaches,
    resolve_timeout, timeout_notices,
)
from partyline.db import Db
from partyline.hierarchy import set_lead
from partyline.restart_scope import skip_reason


class CompletionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = self.tmp.name + '/db'
        self.db = Db(self.path)
        self.db.create_conversation('line', 'line')
        for name in ('old', 'new', 'other'):
            self.db.add_attachment(name, 'line', name, 'fake', [], '/tmp')
            self.db.set_attachment_status(name, 'running', None)
        self.now = time.time()
        self.db._exec('UPDATE attachments SET created_at=?', (self.now - 100,))
        set_lead(self.db, 'line', 'old')
        self.live = {'old', 'new', 'other'}
        self.ident, _ = offer(self.db, 'line', 'old', 'new', 'notes', self.live, now=self.now)
        accept(self.db, 'line', 'new', self.ident, self.live, now=self.now)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def row(self):
        return dict(self.db._exec('SELECT * FROM captain_handovers WHERE id=?', (self.ident,)).fetchone())

    def test_both_orders_and_idempotence(self):
        for first, second in (('old', 'new'), ('new', 'old')):
            with self.subTest(first=first):
                self.db._exec("UPDATE captain_handovers SET state='accepted',from_done=0,to_done=0,"
                              "completed_at=NULL,detach_finished_at=NULL WHERE id=?", (self.ident,))
                row, notice = confirm(self.db, 'line', first, self.ident, now=self.now)
                self.assertIsNone(notice)
                self.assertEqual(row['state'], 'accepted')
                self.assertIn('awaiting', state_text(self.db, second))
                self.assertEqual(self.db.get_attachment('old')['status'], 'running')
                row, notice = confirm(self.db, 'line', first, self.ident, now=self.now)
                self.assertIsNone(notice)
                self.assertEqual(row['state'], 'accepted')
                row, notice = confirm(self.db, 'line', second, self.ident, now=self.now)
                self.assertEqual(row['state'], 'completed')
                self.assertIsNotNone(notice)
                self.assertEqual(len(pending_detaches(self.db)), 1)
                row, notice = confirm(self.db, 'line', second, self.ident, now=self.now)
                self.assertEqual(row['state'], 'completed')
                self.assertIsNone(notice)
        with self.assertRaises(HTTPException):
            offer(self.db, 'line', 'new', 'old', 'next', self.live, now=self.now)
        next_id, _ = offer(self.db, 'line', 'new', 'other', 'next', self.live, now=self.now)
        self.assertNotEqual(next_id, self.ident)

    def test_auth_and_nonaccepted(self):
        with self.assertRaises(HTTPException) as caught:
            confirm(self.db, 'line', 'other', self.ident)
        self.assertEqual(caught.exception.status_code, 403)
        self.db._exec("UPDATE captain_handovers SET state='cancelled' WHERE id=?", (self.ident,))
        with self.assertRaises(HTTPException) as caught:
            confirm(self.db, 'line', 'old', self.ident)
        self.assertEqual(caught.exception.status_code, 409)

    def test_failure_rolls_back_second_confirmation(self):
        confirm(self.db, 'line', 'old', self.ident, now=self.now)
        self.db._exec("CREATE TRIGGER fail_completion BEFORE UPDATE OF state ON captain_handovers "
                      "WHEN NEW.state='completed' BEGIN SELECT RAISE(ABORT, 'simulated'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            confirm(self.db, 'line', 'new', self.ident, now=self.now)
        self.assertEqual((self.row()['state'], self.row()['from_done'], self.row()['to_done']),
                         ('accepted', 1, 0))
        self.assertEqual(pending_detaches(self.db), [])

    def test_timeout_once_and_human_resolution(self):
        confirm(self.db, 'line', 'new', self.ident, now=self.now)
        self.assertEqual(timeout_notices(self.db, self.now + CONFIRM_TIMEOUT_SECONDS - 1), [])
        messages = timeout_notices(self.db, self.now + CONFIRM_TIMEOUT_SECONDS)
        self.assertEqual(len(messages), 1)
        self.assertIn('old', messages[0]['body'])
        self.assertEqual(timeout_notices(self.db, self.now + CONFIRM_TIMEOUT_SECONDS + 1), [])
        self.assertEqual(self.db.get_attachment('old')['status'], 'running')
        resolve_timeout(self.db, 'line', self.ident, now=self.now + CONFIRM_TIMEOUT_SECONDS)
        self.assertEqual(self.row()['state'], 'cancelled')
        self.assertEqual(self.db.get_attachment('old')['status'], 'running')

    def test_restart_recovery_and_restart_plan_skip(self):
        confirm(self.db, 'line', 'old', self.ident, now=self.now)
        confirm(self.db, 'line', 'new', self.ident, now=self.now + 1)
        self.db.close()
        self.db = Db(self.path)
        with self.assertRaises(HTTPException):
            ensure_handover_detached(self.db, 'old')
        self.assertEqual(skip_reason(self.db, self.db.get_attachment('old'), self.now),
                         'completed captain handover')
        # A restart planned after completion but before detach must also skip it.
        self.assertEqual(skip_reason(self.db, self.db.get_attachment('old'), self.now + 2),
                         'completed captain handover')
        runtime = SimpleNamespace(db=self.db, live={'old': object()}, broadcast=AsyncMock())
        async def detach(runtime, att_id):
            self.assertEqual(att_id, 'old')
            self.db.set_attachment_status(att_id, 'detached', None)
            runtime.live.pop(att_id)
        with patch('partyline.captain_handover_completion.detach_attachment', side_effect=detach) as stop:
            asyncio.run(maintenance_once(runtime))
            asyncio.run(maintenance_once(runtime))
        self.assertEqual(stop.await_count, 1)
        self.assertIsNone(self.db.get_attachment('old'))
        self.assertNotIn('old', [a['id'] for a in self.db.list_attachments('line')])
        self.assertTrue(self.db.list_messages('line'))
        self.assertIsNotNone(self.row()['detach_finished_at'])
        ensure_handover_detached(self.db, 'old')

    def test_removal_retry_after_restart_and_missing_record(self):
        confirm(self.db, 'line', 'old', self.ident, now=self.now)
        confirm(self.db, 'line', 'new', self.ident, now=self.now)
        self.db.set_attachment_status('old', 'detached', None)
        runtime = SimpleNamespace(db=self.db, live={}, broadcast=AsyncMock())
        with patch('partyline.captain_handover_completion.remove_stopped_record',
                   new_callable=AsyncMock, side_effect=RuntimeError('interrupted')):
            asyncio.run(maintenance_once(runtime))
        self.assertIsNone(self.row()['detach_finished_at'])
        self.db.close()
        self.db = Db(self.path)
        runtime.db = self.db
        asyncio.run(maintenance_once(runtime))
        self.assertIsNone(self.db.get_attachment('old'))
        self.assertIsNotNone(self.row()['detach_finished_at'])
        self.assertTrue(self.db.list_messages('line'))
        self.db._exec('UPDATE captain_handovers SET detach_finished_at=NULL WHERE id=?', (self.ident,))
        asyncio.run(maintenance_once(runtime))
        self.assertIsNotNone(self.row()['detach_finished_at'])

    def test_completion_http_and_person_resolution(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from partyline.hierarchy_routes import hierarchy_router

        app = FastAPI()
        runtime = SimpleNamespace(db=self.db, live={}, resume_locks={}, broadcast=AsyncMock())
        app.include_router(hierarchy_router(runtime))
        old = SimpleNamespace(kind='machine', conv_id='line', attachment_id='old')
        new = SimpleNamespace(kind='machine', conv_id='line', attachment_id='new')
        with patch('partyline.captain_handover.request_principal', side_effect=[old, new]), \
             patch('partyline.captain_handover_completion._try_detach', new_callable=AsyncMock), \
             TestClient(app) as client:
            first = client.post('/api/conversations/line/handover/complete', json={'handover_id': self.ident})
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(first.json()['state'], 'accepted')
            self.assertTrue(first.json()['from_done'])
            second = client.post('/api/conversations/line/handover/complete',
                                 json={'handover_id': self.ident})
            self.assertEqual(second.status_code, 200, second.text)
            self.assertEqual(second.json()['state'], 'completed')
        self.db._exec("UPDATE captain_handovers SET state='accepted',timeout_notified_at=? WHERE id=?",
                      (self.now, self.ident))
        with patch('partyline.captain_handover_completion.request_principal',
                   return_value=SimpleNamespace(kind='machine')), TestClient(app) as client:
            denied = client.post('/api/conversations/line/handover/resolve', json={'handover_id': self.ident})
        self.assertEqual(denied.status_code, 403)
        with patch('partyline.captain_handover_completion.request_principal',
                   return_value=SimpleNamespace(kind='user')), TestClient(app) as client:
            resolved = client.post('/api/conversations/line/handover/resolve',
                                   json={'handover_id': self.ident})
        self.assertEqual(resolved.status_code, 200, resolved.text)
        self.assertEqual(resolved.json()['state'], 'cancelled')

    def test_detach_intent_never_stops_a_reappointed_captain(self):
        from partyline.captain_handover_completion import finish_detach

        confirm(self.db, 'line', 'old', self.ident, now=self.now)
        confirm(self.db, 'line', 'new', self.ident, now=self.now)
        set_lead(self.db, 'line', 'old')
        runtime = SimpleNamespace(db=self.db, live={'old': object()})
        with patch('partyline.captain_handover_completion.detach_attachment', new_callable=AsyncMock) as stop:
            with self.assertRaises(HTTPException):
                asyncio.run(finish_detach(runtime, self.row()))
        self.assertEqual(stop.await_count, 0)
        self.assertIsNone(self.row()['detach_finished_at'])

    def test_detach_failure_is_retried_and_timeout_broadcast_failure_does_not_block_it(self):
        confirm(self.db, 'line', 'old', self.ident, now=self.now)
        confirm(self.db, 'line', 'new', self.ident, now=self.now)
        self.db._exec("INSERT INTO captain_handovers(id,conv_id,from_attachment_id,to_attachment_id,"
                      "debrief,state,offered_at,accepted_at) VALUES('waiting','line','old','new','notes',"
                      "'accepted',?,?)", (self.now - 4000, self.now - 4000))
        runtime = SimpleNamespace(db=self.db, live={'old': object()},
                                  broadcast=AsyncMock(side_effect=RuntimeError('offline')))
        attempts = []
        async def detach(runtime, att_id):
            attempts.append(att_id)
            if len(attempts) == 1:
                raise HTTPException(503, 'busy')
            self.db.set_attachment_status(att_id, 'detached', None)
            runtime.live.pop(att_id)
        with patch('partyline.captain_handover_completion.detach_attachment', side_effect=detach):
            asyncio.run(maintenance_once(runtime))
            self.assertIsNone(self.row()['detach_finished_at'])
            asyncio.run(maintenance_once(runtime))
        self.assertEqual(attempts, ['old', 'old'])
        self.assertIsNotNone(self.row()['detach_finished_at'])
        self.assertEqual(runtime.broadcast.await_count, 2)
