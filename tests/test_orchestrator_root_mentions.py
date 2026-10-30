"""A task process reaches its root captain, and its brief says how."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from partyline.auth_store import create_user
from partyline.attachment_lifecycle import remove_stopped_record
from partyline.orchestrator_contracts import MessageTaskIn, ReviewRequestIn
from partyline.orchestrator_handles import message_task
from partyline.orchestrator_service import request_review
from partyline.orchestrator_pack import task_pack
from tests.orchestrator_fixture import TaskFixture


class RootMentionTest(TaskFixture):
    async def say(self, body):
        message = self.db.add_message(self.conv_id, self.worker.name, 'agent', body)
        await self.runtime.__class__.route_mentions(self.runtime, self.conv_id, message)
        return message

    async def setUp_task(self):
        await self.create()
        self.runtime.route_mentions = type(self.runtime).route_mentions.__get__(self.runtime)

    def posts(self, conv_id):
        return self.db.message_page(conv_id, limit=100)[0]

    async def test_implementer_reaches_root_captain(self):
        await self.setUp_task()
        self.runtime.live['captain'].deliver = AsyncMock(return_value=True)
        await self.say('done @captain')
        self.runtime.live['captain'].deliver.assert_awaited()
        relayed = [m for m in self.db.messages_after('root', 0)
                   if m.get('audience_attachment_id') == 'captain']
        self.assertTrue(relayed)
        self.assertEqual(relayed[-1]['source_conv_id'], self.conv_id)

    async def test_removed_and_reattached_captain_with_sentence_punctuation(self):
        await self.setUp_task()
        self.db._exec("UPDATE attachments SET status='detached' WHERE id='captain'")
        self.runtime.live.pop('captain')
        await remove_stopped_record(self.db, 'captain')
        self.db.add_attachment('new-captain', 'root', 'captain', 'fake', ['fake'], self.repo, 'new')
        self.db._exec("UPDATE attachments SET is_lead=1,status='running' WHERE id='new-captain'")
        adapter = SimpleNamespace(att={'runtime_owner': 'new'}, deliver=AsyncMock(return_value=True))
        self.runtime.live['new-captain'] = adapter
        await self.say('done @captain.')
        adapter.deliver.assert_awaited()
        self.assertTrue([m for m in self.db.messages_after('root', 0)
                         if m.get('audience_attachment_id') == 'new-captain'
                         and m['body'] == 'done @captain.'])
        self.assertFalse([m for m in self.posts(self.conv_id) if 'reached nobody' in m['body']])

    async def test_task_to_root_exchange_is_hidden_from_people_on_the_root_line(self):
        await self.setUp_task()
        self.runtime.live['captain'].deliver = AsyncMock(return_value=True)
        await self.say('done @captain')
        # The root captain's digest still carries it; people read it on the task line only.
        digest = [m['body'] for m in self.db.messages_after('root', 0)]
        self.assertIn('done @captain', digest)
        self.assertNotIn('done @captain', [m['body'] for m in self.posts('root')])
        copy = [m for m in self.db.messages_after('root', 0) if m['body'] == 'done @captain'][0]
        self.assertIsNone(self.db.message_by_id('root', copy['id']))
        self.assertIn('done @captain', [m['body'] for m in self.posts(self.conv_id)])
        shown = [call.args[1].message.body for call in self.runtime.broadcast.await_args_list
                 if call.args[0] == 'root' and hasattr(call.args[1], 'message')]
        self.assertNotIn('done @captain', shown)

    async def test_root_message_to_a_task_is_not_echoed_on_the_root_line(self):
        await self.create()
        await message_task(self.runtime, self.captain, self.conv_id,
                           MessageTaskIn(text='carry on', to='implementer'))
        self.assertFalse([m for m in self.posts('root') if 'carry on' in m['body']])
        self.assertTrue([m for m in self.posts(self.conv_id) if 'carry on' in m['body']])

    async def test_other_line_process_is_still_held_back(self):
        await self.setUp_task()
        self.db.create_conversation('other', 'Other')
        self.db.add_attachment('peer', 'other', 'peer', 'fake', ['fake'], self.repo, 'owner')
        self.db._exec("UPDATE attachments SET status='running' WHERE id='peer'")
        self.db._exec("UPDATE conversations SET parent_id='root' WHERE id='other'")
        self.runtime.live['peer'] = SimpleNamespace(att={'runtime_owner': 'owner'})
        await self.say('hi @peer')
        self.assertFalse([m for m in self.posts('other') if m.get('audience_attachment_id') == 'peer'])
        notices = [m['body'] for m in self.posts(self.conv_id) if m['sender_type'] == 'system']
        self.assertTrue(any('@captain' in n and 'root captain' in n for n in notices))

    async def test_unresolved_mention_gets_hint(self):
        await self.setUp_task()
        await self.say('ping @argon')
        hints = [m for m in self.posts(self.conv_id)
                 if 'reached nobody' in m['body']
                 and m['audience_attachment_id'] == self.worker.attachment_id]
        self.assertEqual(len(hints), 1)
        self.assertIn('@captain', hints[0]['body'])

    async def test_unresolved_captain_name_explains_routing_failure(self):
        from partyline.mention_relay import hint_root_captain

        await self.setUp_task()
        message = self.db.add_message(self.conv_id, self.worker.name, 'agent', 'ping @captain')
        with patch('partyline.mention_relay.known_mention_names', return_value=set()):
            await hint_root_captain(self.runtime, self.conv_id, message, {'captain'})
        hints = [m['body'] for m in self.posts(self.conv_id) if 'reached nobody' in m['body']]
        self.assertEqual(len(hints), 1)
        self.assertIn('could not be routed', hints[0])
        self.assertNotIn('mention @captain', hints[0])

    async def test_pack_names_root_line_and_captain(self):
        await self.create()
        pack = task_pack(self.db, self.conv_id, 'implementer')
        self.assertIn('«Root»', pack)
        self.assertIn('mention @captain', pack)
        self.assertIn('line names are not mentionable', pack)

    async def test_pack_says_no_live_captain_when_lead_not_live(self):
        await self.create()
        self.db._exec("UPDATE attachments SET status='exited' WHERE id='captain'")
        pack = task_pack(self.db, self.conv_id, 'implementer')
        self.assertIn('no live captain', pack)
        self.assertNotIn('mention @captain', pack)

    async def test_person_and_absent_local_process_get_no_hint(self):
        await self.create()
        create_user(self.db, 'g@example.com', 'greg', 'x')
        sha = self.commit()
        await request_review(self.runtime, self.worker, self.conv_id,
                             ReviewRequestIn(sha=sha, what='feature', where='code'))
        reviewer = self.db.get_attachment(self.row()['reviewer_id'])
        self.db._exec("UPDATE attachments SET status='exited' WHERE id=?", (reviewer['id'],))
        self.runtime.route_mentions = type(self.runtime).route_mentions.__get__(self.runtime)
        self.runtime.live['captain'].deliver = AsyncMock(return_value=True)
        await self.say(f"done @{reviewer['name']} @greg @all")
        self.assertFalse([m for m in self.posts(self.conv_id) if 'reached nobody' in m['body']])
