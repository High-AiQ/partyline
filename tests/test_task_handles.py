"""Task processes are named after their task; the root messages a task by id."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException

from partyline.auth_guard import Principal
from partyline.mcp.tools_tasks import call, tool_list
from partyline.mention_relay import relay_mentions
from partyline.orchestrator_contracts import MessageTaskIn, ReviewRequestIn
from partyline.orchestrator_handles import message_task, pick_tag
from partyline.orchestrator_pack import task_pack
from partyline.orchestrator_service import request_review
from partyline.orchestrator_store import tasks
from partyline.pack_blocks import ORCHESTRATOR
from partyline.preset_traits import coerce_preset
from partyline.staffing import staffing_report
from tests.orchestrator_fixture import TaskFixture


class TaskHandleTest(TaskFixture):
    async def review(self):
        await self.create()
        await request_review(self.runtime, self.worker, self.conv_id,
                             ReviewRequestIn(sha=self.commit(), what='built', where='code'))
        return self.row()

    def messages(self, conv):
        return self.db.message_page(conv, limit=100)[0]

    async def test_new_tasks_get_impl_and_review_handles_sharing_one_tag(self):
        row = await self.review()
        tag = row['tag']
        self.assertRegex(tag, r'^[0-9a-f]{6}$')
        self.assertEqual(self.db.get_attachment(row['implementer_id'])['name'], f'impl-{tag}')
        self.assertEqual(self.db.get_attachment(row['reviewer_id'])['name'], f'review-{tag}')
        self.assertEqual((row['implementer_handle'], row['reviewer_handle']),
                         (f'impl-{tag}', f'review-{tag}'))
        listed = tasks(self.db, 'root')[0]
        self.assertEqual((listed['implementer_handle'], listed['reviewer_handle']),
                         (f'impl-{tag}', f'review-{tag}'))

    async def test_two_tasks_with_one_preset_have_different_handles(self):
        first = await self.create()
        second = await self.create()
        self.assertNotEqual(first['implementer_handle'], second['implementer_handle'])
        self.assertNotIn('builder', first['implementer_handle'])

    async def test_tag_lengthens_when_it_collides(self):
        await self.create()
        tag = self.row()['tag']
        db = self.db
        other = self.conv_id  # the same id prefix collides on the short tag
        self.assertEqual(pick_tag(db, other)[:6], tag)
        self.assertGreater(len(pick_tag(db, other)), 6)
        self.assertEqual(pick_tag(db, 'plain-line'), pick_tag(db, 'plain-line'))

    async def test_preset_is_recorded_and_shown_in_the_contract(self):
        row = await self.review()
        self.assertEqual(self.db.get_attachment(row['implementer_id'])['preset'], 'builder')
        self.assertEqual(self.db.get_attachment(row['reviewer_id'])['preset'], 'inspector')
        self.assertEqual(row['implementer_preset'], 'builder')
        presets = [coerce_preset(p) for p in self.db.list_presets()]
        report = staffing_report(self.db, 'root')
        matched = {p['handle']: p['matched_preset'] and p['matched_preset']['name']
                   for p in report['processes']}
        self.assertEqual(matched.get(row['implementer_handle']), 'builder')
        self.assertEqual(matched.get(row['reviewer_handle']), 'inspector')
        self.assertTrue(presets)

    async def test_message_task_reaches_implementer_and_reviewer(self):
        row = await self.review()
        for to, ident in (('implementer', row['implementer_id']), ('reviewer', row['reviewer_id'])):
            result = await message_task(self.runtime, self.captain, self.conv_id,
                                        MessageTaskIn(text=f'hello {to}', to=to))
            self.assertEqual(result['conv_id'], self.conv_id)
            sent = [m for m in self.messages(self.conv_id) if f'hello {to}' in m['body']]
            self.assertEqual(sent[-1]['audience_attachment_id'], ident)
            self.assertIn(self.db.get_attachment(ident)['name'], sent[-1]['body'])
            # The captain speaks in its own name; a person could not tell "system" from astra.
            self.assertEqual((sent[-1]['sender'], sent[-1]['sender_type']), ('captain', 'agent'))
            self.assertNotIn('Message from', sent[-1]['body'])
        await message_task(self.runtime, self.human, self.conv_id, MessageTaskIn(text='from a person'))
        spoken = [m for m in self.messages(self.conv_id) if 'from a person' in m['body']][-1]
        self.assertEqual((spoken['sender'], spoken['sender_type']), ('human', 'human'))

    async def test_message_task_409_without_a_live_process_and_403_for_others(self):
        await self.create('captain')
        with self.assertRaises(HTTPException) as caught:
            await message_task(self.runtime, self.captain, self.conv_id,
                               MessageTaskIn(text='x', to='reviewer'))
        self.assertEqual(caught.exception.status_code, 409)
        self.db._exec("UPDATE attachments SET status='exited' WHERE id=?", (self.worker.attachment_id,))
        with self.assertRaises(HTTPException) as caught:
            await message_task(self.runtime, self.captain, self.conv_id, MessageTaskIn(text='x'))
        self.assertEqual(caught.exception.status_code, 409)
        self.db._exec("UPDATE attachments SET status='running' WHERE id=?", (self.worker.attachment_id,))
        reviewer = Principal(kind='machine', name='r', conv_id=self.conv_id, attachment_id='r')
        for actor in (self.worker, reviewer):
            with self.assertRaises(HTTPException) as caught:
                await message_task(self.runtime, actor, self.conv_id, MessageTaskIn(text='x'))
            self.assertEqual(caught.exception.status_code, 403)
        with self.assertRaises(HTTPException) as caught:
            await message_task(self.runtime, self.captain, 'nope', MessageTaskIn(text='x'))
        self.assertEqual(caught.exception.status_code, 404)

    async def test_message_task_route_and_tool(self):
        row = await self.create()
        self.actor = self.captain
        response = self.client.post(f'/api/conversations/{self.conv_id}/task/message',
                                    json={'text': 'by route'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['implementer_handle'], row['implementer_handle'])
        self.assertEqual(self.client.post(f'/api/conversations/{self.conv_id}/task/message',
                                          json={'text': ''}).status_code, 422)
        state = {'actions': ['message_task']}
        self.assertIn('conv_id', tool_list(state)[0]['inputSchema']['required'])
        client = SimpleNamespace(home='root', request=lambda *a: a)
        self.assertEqual(call(client, 'message_task', {'conv_id': 'c1', 'text': 'hi', 'to': 'reviewer'},
                              state), ('POST', '/api/conversations/c1/task/message',
                                       {'text': 'hi', 'to': 'reviewer'}))

    async def test_captain_cannot_ring_another_tasks_worker_from_a_task_line(self):
        first = await self.create()
        second = await self.create()
        second_line = self.conv_id
        message = self.db.add_message(second_line, 'captain', 'agent',
                                      f"@{first['implementer_handle']} please fix")
        self.db._exec('UPDATE messages SET source_attachment_id=?,source_conv_id=? WHERE id=?',
                      ('captain', 'root', message['id']))
        message = self.db.message_page(second_line, limit=1)[0][-1]
        before = len(self.messages(first['conv_id']))
        await relay_mentions(self.runtime, second_line, message, {first['implementer_handle'].lower()})
        self.assertEqual(len(self.messages(first['conv_id'])), before)
        notices = [m for m in self.messages('root') if 'held back' in m['body']]
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]['audience_attachment_id'], 'captain')
        self.assertIn(second['implementer_handle'], notices[0]['body'])
        self.assertIn('message_task', notices[0]['body'])

    async def test_other_speakers_and_root_line_mentions_are_unaffected(self):
        first = await self.create()
        await self.create()
        self.runtime.route_mentions = AsyncMock()
        names = {first['implementer_handle'].lower()}
        # A task process is not the root captain: the existing withheld notice applies.
        message = self.db.add_message(self.conv_id, self.worker.name, 'agent', 'hi')
        await relay_mentions(self.runtime, self.conv_id, message, names)
        self.assertFalse([m for m in self.messages('root') if 'held back' in m['body']])
        self.assertTrue([m for m in self.messages(self.conv_id) if 'not this one' in m['body']])
        # The root captain speaking on its own line reaches any task below it.
        message = self.db.add_message('root', 'captain', 'agent', 'hi')
        self.db._exec('UPDATE messages SET source_attachment_id=? WHERE id=?', ('captain', message['id']))
        message = self.db.message_page('root', limit=1)[0][-1]
        await relay_mentions(self.runtime, 'root', message, names)
        self.assertTrue([m for m in self.messages(first['conv_id'])
                         if m['audience_attachment_id'] == first['implementer_id']])

    async def test_packs_name_the_handles_and_message_task(self):
        row = await self.review()
        implementer = task_pack(self.db, self.conv_id, 'implementer')
        self.assertIn(f"Your handle is {row['implementer_handle']}", implementer)
        self.assertIn(f"The reviewer of this task is {row['reviewer_handle']}", implementer)
        reviewer = task_pack(self.db, self.conv_id, 'reviewer')
        self.assertIn(f"Your handle is {row['reviewer_handle']}", reviewer)
        self.assertIn(f"The implementer of this task is {row['implementer_handle']}", reviewer)
        for text in ('impl-<tag>', 'review-<tag>', 'message_task(conv_id, text, to='):
            self.assertIn(text, ORCHESTRATOR)

    async def test_legacy_task_without_a_tag_keeps_preset_handles(self):
        await self.create()
        self.db._exec('UPDATE task_reviews SET tag=NULL WHERE conv_id=?', (self.conv_id,))
        row = await request_review(self.runtime, self.worker, self.conv_id,
                                   ReviewRequestIn(sha=self.commit(), what='b', where='c'))
        self.assertEqual(row['reviewer_handle'], 'inspector')
        self.assertIn('Your handle is inspector', task_pack(self.db, self.conv_id, 'reviewer'))
