"""A detached task implementer is brought back by the root captain or a person."""

from unittest.mock import MagicMock

from fastapi import HTTPException

from partyline.line_process_routes import _revive_hint, detach_attachment
from partyline.mcp import tools_tasks
from partyline.orchestrator_handles import message_task
from partyline.orchestrator_contracts import MessageTaskIn
from partyline.orchestrator_store import refuse_task_attach
from tests.orchestrator_fixture import TaskFixture


class ImplementerRestartTest(TaskFixture):
    def detach(self):
        ident = self.row()['implementer_id']
        self.db._exec("UPDATE attachments SET status='exited' WHERE id=?", (ident,))
        self.runtime.live.pop(ident, None)
        return ident

    def url(self):
        return f'/api/conversations/{self.conv_id}/task/implementer'

    async def test_a_non_root_machine_is_refused(self):
        await self.create()
        self.detach()
        self.actor = self.worker
        self.assertEqual(self.client.post(self.url()).status_code, 403)

    async def test_a_live_implementer_is_a_conflict(self):
        await self.create()
        response = self.client.post(self.url())
        self.assertEqual(response.status_code, 409)
        self.assertIn('already running', response.json()['detail'])

    async def test_restart_relaunches_notifies_and_returns_the_task(self):
        await self.create()
        ident = self.detach()
        self.actor = self.captain
        self.runtime.returns = MagicMock()
        response = self.client.post(self.url())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['conv_id'], self.conv_id)
        self.assertEqual(self.db.get_attachment(ident)['status'], 'running')
        notices = [m['body'] for m in self.db.list_messages(self.conv_id)
                   if m['audience_attachment_id'] == ident]
        self.runtime.returns.handed_to.assert_called_once_with('captain', ident)
        self.assertTrue(any('resumed by captain; continue the task:' in body for body in notices), notices)

    async def test_a_blocked_task_and_a_person_are_allowed(self):
        await self.create()
        self.db._exec("UPDATE task_reviews SET status='blocked' WHERE conv_id=?", (self.conv_id,))
        self.detach()
        self.assertEqual(self.client.post(self.url()).status_code, 200)

    async def test_a_task_out_of_work_or_missing_is_refused(self):
        await self.create()
        self.db._exec("UPDATE task_reviews SET status='done' WHERE conv_id=?", (self.conv_id,))
        self.detach()
        self.assertEqual(self.client.post(self.url()).status_code, 409)
        self.assertEqual(self.client.post('/api/conversations/nope/task/implementer').status_code, 404)

    async def test_refusals_name_the_recovery(self):
        await self.create()
        self.detach()
        with self.assertRaises(HTTPException) as dead:
            await message_task(self.runtime, self.captain, self.conv_id, MessageTaskIn(text='hi'))
        self.assertIn('no live implementer to message; call restart_implementer', dead.exception.detail)
        with self.assertRaises(HTTPException) as staffed:
            refuse_task_attach(self.db, self.conv_id)
        self.assertIn('restart_implementer / restart_reviewer', staffed.exception.detail)
        self.assertIn('restart_implementer', _revive_hint(self.db, self.row()['implementer_id']))
        self.assertEqual(_revive_hint(self.db, 'captain'), '')

    async def test_the_tool_is_registered_with_a_conv_id_schema(self):
        listed = tools_tasks.tool_list({'actions': ['restart_implementer']})
        self.assertEqual(listed[0]['inputSchema']['required'], ['conv_id'])
        self.assertIn('restart_implementer', tools_tasks.OPERATIONS)

    async def test_the_detach_hint_only_names_an_op_that_would_accept(self):
        await self.create()
        impl = self.row()['implementer_id']
        self.db._exec("UPDATE task_reviews SET status='done' WHERE conv_id=?", (self.conv_id,))
        self.assertEqual(_revive_hint(self.db, impl), '')
        self.db._exec("UPDATE task_reviews SET status='in_review',reviewer_id='rv' WHERE conv_id=?",
                      (self.conv_id,))
        self.assertEqual(_revive_hint(self.db, 'rv'), '; revive it with restart_reviewer')
        self.assertEqual(_revive_hint(self.db, impl), '')
        self.db._exec("UPDATE task_reviews SET policy='captain' WHERE conv_id=?", (self.conv_id,))
        self.assertEqual(_revive_hint(self.db, 'rv'), '')

    async def test_only_the_person_called_detach_says_how_to_revive(self):
        await self.create()
        ident = self.row()['implementer_id']
        await detach_attachment(self.runtime, ident, survivors=False)
        self.assertFalse(any('restart_implementer' in m['body'] for m in self.db.list_messages(self.conv_id)))
        self.db._exec("UPDATE attachments SET status='running' WHERE id=?", (ident,))
        await self.resume(ident)
        await detach_attachment(self.runtime, ident, survivors=False, hint=True)
        self.assertTrue(any('detached; revive it with restart_implementer' in m['body']
                            for m in self.db.list_messages(self.conv_id)))
