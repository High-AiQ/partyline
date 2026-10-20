"""A blocked task returns to implementing when its implementer resumes work."""

import time
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException

from partyline.hook_routes import handle_hook
from partyline.mcp.tools_tasks import call
from partyline.orchestrator_contracts import BlockedIn, ResumeIn
from partyline.orchestrator_pack import task_pack
from partyline.orchestrator_stall import blocked, resume_work
from partyline.reports import get
from partyline.return_path import ReturnPath
from tests.orchestrator_fixture import TaskFixture


class ResumeTest(TaskFixture):
    async def block(self):
        await self.create('none')
        await blocked(self.runtime, self.worker, self.conv_id, BlockedIn(reason='dependency'))

    def say(self, sender_type, sender, *, source=None, audience=None, ahead=1.0):
        message = self.db.add_message(self.conv_id, sender, sender_type, 'go on')
        self.db._exec('UPDATE messages SET created_at=?,source_conv_id=?,audience_attachment_id=? '
                      'WHERE id=?', (time.time() + ahead, source, audience, message['id']))

    async def begin(self):
        request = Mock(json=AsyncMock(return_value={'hookEventName': 'UserPromptSubmit'}))
        att = self.db.get_attachment(self.worker.attachment_id)
        presence = Mock(began=AsyncMock())
        await handle_hook(self.runtime, presence, att['id'], att['runtime_owner'], request)

    async def test_explicit_resume_notifies_root_once_and_rearms_the_reminder(self):
        await self.block()
        blocked_report = self.row()['report_id']
        self.runtime.broadcast_all.reset_mock()
        row = await resume_work(self.runtime, self.worker, self.conv_id, ResumeIn(note='API is back'))
        self.assertEqual((row['status'], row['stall_stage'], row['report_id']), ('implementing', 0, None))
        self.assertEqual(self.db.get_conversation(self.conv_id)['task_status'], 'implementing')
        self.runtime.broadcast_all.assert_awaited()
        # The pending blocked report is updated in place: one report, one wake.
        root = [m for m in self.db.message_page('root', limit=100)[0] if 'needs attention' in m['body']]
        self.assertEqual(len(root), 1)
        self.assertIn('unblocked: API is back', get(self.db, blocked_report)['body'])
        with self.assertRaises(HTTPException) as caught:
            await resume_work(self.runtime, self.worker, self.conv_id, ResumeIn(note='again'))
        self.assertEqual(caught.exception.status_code, 409)
        returns = self.runtime.returns = ReturnPath(self.runtime)
        returns.grace = 0
        with patch('partyline.return_path.wait_until_quiet', AsyncMock(return_value=True)):
            await returns.turn_ended(self.worker.attachment_id)
            await returns.drain()
        self.assertEqual(self.row()['stall_stage'], 1)

    async def test_resume_without_note_sends_no_report(self):
        await self.block()
        before = len(self.db.message_page('root', limit=100)[0])
        await resume_work(self.runtime, self.worker, self.conv_id, ResumeIn())
        self.assertEqual(len(self.db.message_page('root', limit=100)[0]), before)

    async def test_http_resume_is_implementer_only_and_needs_blocked(self):
        await self.create()
        url = f'/api/conversations/{self.conv_id}/task/resume'
        self.actor = self.worker
        self.assertEqual(self.client.post(url, json={}).status_code, 409)
        await blocked(self.runtime, self.worker, self.conv_id, BlockedIn(reason='dependency'))
        for actor in (self.captain, self.human):
            self.actor = actor
            self.assertEqual(self.client.post(url, json={}).status_code, 403)
        self.actor = self.worker
        self.assertEqual(self.client.post(url, json={'note': ''}).status_code, 422)
        response = self.client.post(url, json={'note': 'unblocked'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], 'implementing')

    async def test_mcp_tool_and_pack(self):
        await self.create()
        client = Mock(home=self.conv_id)
        call(client, 'resume_work', {'note': 'ok'}, {'actions': ['resume_work']})
        client.request.assert_called_once_with(
            'POST', f'/api/conversations/{self.conv_id}/task/resume', {'note': 'ok'})
        self.assertIn('call resume_work(note)', task_pack(self.db, self.conv_id, 'implementer'))

    async def test_turn_after_captain_or_person_message_resumes(self):
        for sender_type, sender, source in (('human', 'greg', None), ('agent', 'captain', 'root')):
            with self.subTest(sender=sender):
                await self.block()
                await self.begin()
                self.assertEqual(self.row()['status'], 'blocked')
                self.say(sender_type, sender, source=source)
                self.runtime.broadcast_all.reset_mock()
                await self.begin()
                self.assertEqual(self.row()['status'], 'implementing')
                self.runtime.broadcast_all.assert_awaited()
                self.db._exec('DELETE FROM messages WHERE conv_id=?', (self.conv_id,))
                self.db._exec('DELETE FROM task_reviews WHERE conv_id=?', (self.conv_id,))
                self.db._exec('DELETE FROM conversations WHERE id=?', (self.conv_id,))

    async def test_reminders_old_and_other_messages_do_not_resume(self):
        await self.block()
        self.say('system', 'system', audience=self.worker.attachment_id)
        self.say('human', 'greg', ahead=-60)
        self.say('human', 'greg', audience='someone-else')
        self.say('agent', 'peer', source=self.conv_id)
        await self.begin()
        self.assertEqual(self.row()['status'], 'blocked')
        await resume_work(self.runtime, self.worker, self.conv_id, ResumeIn())
        await self.begin()  # not blocked: nothing happens
        self.assertEqual(self.row()['status'], 'implementing')
