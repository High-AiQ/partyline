"""Database write access can approve one restart without a human credential."""

import hashlib
import sqlite3
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from partyline import operator_restart
from tests import test_restart_requests as requests


class OperatorRestartTest(unittest.TestCase):
    setUp = requests.RestartRequestTest.setUp
    file = requests.RestartRequestTest.file
    go_live = requests.RestartRequestTest.go_live

    def approve(self, ident, token, host="127.0.0.1"):
        with TestClient(self.client.app, client=(host, 1234)) as client:
            return client.post('/api/restart-request/operator-approve',
                               json={'request_id': ident, 'token': token})

    def test_local_operator_saves_every_line_and_schedules_the_same_restart(self):
        ident = self.file(self.captain).json()['id']
        self.go_live('cap')
        self.go_live('wrk')
        self.db.create_conversation('other', 'Other')
        self.db.add_attachment('other-worker', 'other', 'other', 'fake', ['fake'], '/tmp')
        self.db._exec("UPDATE attachments SET status='running' WHERE id='other-worker'")
        self.go_live('other-worker')
        token = operator_restart.issue(self.db.path, ident)
        row = self.db._exec('SELECT * FROM operator_restart_approvals').fetchone()
        self.assertEqual(row['token_hash'], hashlib.sha256(token.encode()).hexdigest())
        self.assertNotIn(token, str(dict(row)))
        with patch('partyline.restart_requests.service_unit', return_value='partyline-test.service'), \
                patch('partyline.restart_requests.schedule_unit_restart', return_value=True) as schedule:
            result = self.approve(ident, token)
        self.assertEqual(result.status_code, 200, result.text)
        schedule.assert_called_once_with('partyline-test.service')
        plan = self.db.get_restart_plan()
        self.assertEqual(plan['mode'], 'automatic')
        self.assertEqual(set(plan['attachment_ids']), {'cap', 'wrk', 'other-worker'})
        self.assertIsNone(self.runtime.restart_request)
        self.assertEqual(self.approve(ident, token).status_code, 403)
        self.assertTrue(any('approved by @local-operator' in m['body']
                            for m in self.db.list_messages('line')))

    def test_reading_hash_does_not_authorize_and_machine_route_stays_forbidden(self):
        ident = self.file(self.captain).json()['id']
        token = operator_restart.issue(self.db.path, ident)
        digest = hashlib.sha256(token.encode()).hexdigest()
        self.assertEqual(self.approve(ident, digest[:43]).status_code, 403)
        response = self.client.post(f'/api/restart-request/{ident}/approve', headers=self.captain)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.runtime.restart_request.id, ident)

    def test_grants_are_request_bound_expiring_and_loopback_only(self):
        ident = self.file(self.captain).json()['id']
        token = operator_restart.issue(self.db.path, ident)
        self.assertEqual(self.approve('0' * 12, token).status_code, 403)
        self.assertEqual(self.approve(ident, token, '192.0.2.1').status_code, 403)
        with patch.object(operator_restart.time, 'time', return_value=10**12):
            self.assertEqual(self.approve(ident, token).status_code, 403)
        self.assertEqual(self.runtime.restart_request.id, ident)

    def test_declined_request_cannot_be_resurrected(self):
        ident = self.file(self.captain).json()['id']
        token = operator_restart.issue(self.db.path, ident)
        self.assertEqual(self.client.delete(f'/api/restart-request/{ident}',
                                          headers=self.human).status_code, 200)
        self.assertEqual(self.approve(ident, token).status_code, 404)
        self.assertFalse(operator_restart.consume(self.db, ident, token))

    def test_issuing_does_not_create_missing_databases_or_accept_bad_ids(self):
        with self.assertRaises(ValueError):
            operator_restart.issue(self.db.path, '../invalid')
        with self.assertRaises(sqlite3.OperationalError):
            operator_restart.issue(self.directory.name + '/missing.db', 'a' * 12)


from tests import test_fence as fence_tests


@unittest.skipUnless(fence_tests.BWRAP_SKIP_REASON is None,
                     fence_tests.BWRAP_SKIP_REASON or '')
class OperatorFenceTest(unittest.TestCase):
    setUp = fence_tests.FenceIntegrationTest.setUp
    mirror_root = fence_tests.FenceIntegrationTest.mirror_root
    run_fenced = fence_tests.FenceIntegrationTest.run_fenced

    def test_attached_process_cannot_issue_local_operator_approval(self):
        import sys
        from partyline.db import Db
        from partyline.fence_protect import database_paths

        db = Db(self.directory.name + '/operator.db')
        self.addCleanup(db.close)
        self.att['db_paths'] = database_paths(db)
        ident = 'a' * 12
        code = ('from partyline.operator_restart import issue; '
                f'issue({db.path!r}, {ident!r})')
        result = self.run_fenced(sys.executable, '-c', code)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('readonly', result.stderr.lower())
        self.assertIsNone(db._exec('SELECT * FROM operator_restart_approvals').fetchone())
        token = operator_restart.issue(db.path, ident)
        self.assertTrue(operator_restart.consume(db, ident, token))
