"""complete_handover says whether the handover is finished, and why a side is still awaited."""
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline.captain_handover import accept, offer
from partyline.db import Db
from partyline.hierarchy import set_lead
from partyline.hierarchy_routes import hierarchy_router


class CompleteStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Db(self.tmp.name + '/db')
        self.addCleanup(self.db.close)
        self.db.create_conversation('line', 'line')
        for name in ('old', 'new'):
            self.db.save_preset(name, name, name, 'fake', '', can_manage=True)
            self.db.add_attachment(name, 'line', name, 'fake', [], '/tmp')
            self.db.set_attachment_status(name, 'running', None)
        self.db._exec('UPDATE attachments SET created_at=?', (time.time() - 100,))
        set_lead(self.db, 'line', 'old')
        self.live = {'old', 'new'}
        self.ident, _ = offer(self.db, 'line', 'old', 'new', 'notes', self.live)
        accept(self.db, 'line', 'new', self.ident, self.live)
        self.runtime = SimpleNamespace(db=self.db, live={'old': object(), 'new': object()},
                                       resume_locks={}, broadcast=AsyncMock())
        app = FastAPI()
        app.include_router(hierarchy_router(self.runtime))
        self.client = TestClient(app)

    def complete(self, who):
        actor = SimpleNamespace(kind='machine', conv_id='line', attachment_id=who)
        with patch('partyline.captain_handover.request_principal', return_value=actor), \
             patch('partyline.captain_handover_completion._try_detach', new_callable=AsyncMock):
            reply = self.client.post('/api/conversations/line/handover/complete',
                                     json={'handover_id': self.ident})
        self.assertEqual(reply.status_code, 200, reply.text)
        return reply.json()

    def test_a_half_confirmed_handover_names_who_is_awaited(self):
        first = self.complete('new')
        self.assertFalse(first['completed'])
        self.assertEqual(first['awaiting'], ['old'])
        self.assertEqual(first['old_captain'], 'attached')
        self.assertIn('waiting for old', first['message'])

    def test_both_confirmed_reports_a_finished_handover_to_either_caller(self):
        self.complete('new')
        done = self.complete('old')
        self.assertTrue(done['completed'])
        self.assertEqual((done['state'], done['from_done'], done['to_done']), ('completed', True, True))
        self.assertEqual(done['old_captain'], 'detaching')
        again = self.complete('new')
        self.assertTrue(again['completed'] and again['from_done'] and again['to_done'])

    def test_the_new_captain_completes_when_the_old_one_is_already_gone(self):
        # The old captain was detached before it confirmed: nothing is left to wait for.
        self.db.set_attachment_status('old', 'detached', None)
        del self.runtime.live['old']
        done = self.complete('new')
        self.assertEqual((done['state'], done['from_done'], done['to_done']), ('completed', True, True))
        self.assertTrue(done['completed'])
        self.assertEqual(done['awaiting'], [])
        self.assertIn('Handover completed', done['message'])

    def test_a_detached_old_captain_is_reported_as_detached(self):
        self.complete('new')
        self.complete('old')
        self.db._exec("UPDATE captain_handovers SET detach_finished_at=? WHERE id=?",
                      (time.time(), self.ident))
        self.assertEqual(self.complete('new')['old_captain'], 'detached')
        self.db._exec("DELETE FROM attachments WHERE id='old'")
        final = self.complete('new')
        self.assertEqual(final['old_captain'], 'detached')
        self.assertIn('is detached', final['message'])

    def test_the_old_captain_confirming_after_completion_is_a_harmless_no_op(self):
        self.db.set_attachment_status('old', 'detached', None)
        del self.runtime.live['old']
        first = self.complete('new')
        self.assertTrue(first['completed'])
        before = self.db._exec('SELECT * FROM captain_handovers WHERE id=?', (self.ident,)).fetchone()
        count = "SELECT COUNT(*) FROM messages WHERE body LIKE '%completed by%'"
        notices = self.db._exec(count).fetchone()[0]
        self.runtime.broadcast.reset_mock()
        late = self.complete('old')
        self.assertEqual((late['state'], late['completed']), ('completed', True))
        self.assertTrue(late['from_done'] and late['to_done'])
        self.assertIn('Already completed', late['message'])
        self.assertNotIn('Already completed', first['message'])
        after = self.db._exec('SELECT * FROM captain_handovers WHERE id=?', (self.ident,)).fetchone()
        self.assertEqual(tuple(before), tuple(after))  # same completed_at: not completed twice
        self.assertEqual(self.db._exec(count).fetchone()[0], notices)
        self.runtime.broadcast.assert_not_awaited()

    def test_a_live_old_captain_confirming_after_completion_is_the_same_no_op(self):
        self.complete('new')
        self.complete('old')
        late = self.complete('old')
        self.assertTrue(late['completed'])
        self.assertIn('Already completed', late['message'])


if __name__ == '__main__':
    unittest.main()
