"""A detached task implementer is brought back by the root captain or a person."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from partyline import server
from partyline.adapters import Adapter

from fastapi import HTTPException

from partyline.line_process_routes import _revive_hint, detach_attachment
from partyline.mcp import tools_tasks
from partyline.orchestrator_handles import message_task
from partyline.orchestrator_revive import IMPLEMENTER_STALL_SECONDS
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

    async def test_v2_worker_stalled_after_receiving_work_can_be_restarted(self):
        await self.create()
        ident = self.row()['implementer_id']
        self.db._exec("UPDATE attachments SET adapter='opencode-v2',cli_session='session' WHERE id=?",
                      (ident,))
        self.db._exec("UPDATE presets SET adapter='opencode-v2' WHERE name='builder'")
        live = self.runtime.live[ident]
        live.resume = True
        live._claim_proven = True
        live.last_transcript_progress = 100
        clock = SimpleNamespace(monotonic=lambda: 100 + IMPLEMENTER_STALL_SECONDS)
        with patch.dict(server.ADAPTERS, {"opencode-v2": Adapter}), patch(
                "partyline.orchestrator_revive.time", clock):
            response = self.client.post(self.url())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNot(self.runtime.live[ident], live)
        self.assertEqual(self.db.get_attachment(ident)['status'], 'running')
        self.assertTrue(any('continue the task' in m['body']
                            for m in self.db.list_messages(self.conv_id)))

    async def test_active_v2_worker_gets_an_actionable_conflict(self):
        await self.create()
        ident = self.row()['implementer_id']
        self.db._exec("UPDATE attachments SET adapter='opencode-v2' WHERE id=?", (ident,))
        self.db._exec("UPDATE presets SET adapter='opencode-v2' WHERE name='builder'")
        live = self.runtime.live[ident]
        clock = SimpleNamespace(monotonic=lambda: 2000)
        with patch("partyline.orchestrator_revive.time", clock):
            for age in (0, 5, IMPLEMENTER_STALL_SECONDS - 1):
                live.last_transcript_progress = 2000 - age
                response = self.client.post(self.url())
                self.assertEqual(response.status_code, 409)
                self.assertIn(f'active {age}s ago; message_task it', response.json()['detail'])
                self.assertIs(self.runtime.live[ident], live)

    async def test_missing_progress_or_stale_owner_does_not_allow_restart(self):
        await self.create()
        ident = self.row()['implementer_id']
        self.db._exec("UPDATE attachments SET adapter='opencode-v2' WHERE id=?", (ident,))
        self.db._exec("UPDATE presets SET adapter='opencode-v2' WHERE name='builder'")
        self.assertEqual(self.client.post(self.url()).status_code, 409)
        live = self.runtime.live[ident]
        live.last_transcript_progress = 0
        live.att['runtime_owner'] = 'stale-owner'
        self.assertEqual(self.client.post(self.url()).status_code, 409)

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

    async def test_restart_implementer_stages_queued_mail_before_newer_mail(self):
        await self.create()
        ident = self.detach()
        self.db._exec("UPDATE attachments SET cli_session='session' WHERE id=?", (ident,))
        att = self.db.get_attachment(ident)
        old = self.db.add_message(self.conv_id, 'captain', 'human', f"@{att['name']} older")
        self.db.set_last_seen(ident, old['id'], att['runtime_owner'])
        await self.db.queue_delivery_ids(ident, [old['id']], att['runtime_owner'])
        new = self.db.add_message(self.conv_id, 'captain', 'human', f"@{att['name']} newer")
        self.actor = self.captain
        response = self.client.post(self.url())
        self.assertEqual(response.status_code, 200, response.text)
        ids = [message['id'] for message in self.runtime.live[ident].startup_messages]
        self.assertLess(ids.index(old['id']), ids.index(new['id']))

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
        self.assertIn('captain(op="restart_implementer" or "restart_reviewer")', staffed.exception.detail)
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
        self.assertEqual(_revive_hint(self.db, 'rv'), '; revive it with captain(op="restart_reviewer")')
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
        self.assertTrue(any('detached; revive it with captain(op="restart_implementer")' in m['body']
                            for m in self.db.list_messages(self.conv_id)))
