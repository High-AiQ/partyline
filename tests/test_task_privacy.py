"""The root captain's messages to task processes stay off the root transcript."""

from unittest.mock import AsyncMock

from partyline.contracts import MessageEvent, MessageResponse
from tests.orchestrator_fixture import TaskFixture


class TaskPrivacyTest(TaskFixture):
    async def say_on_root(self, body):
        """The root captain speaks; the event goes through the real fan-out."""
        self.runtime.broadcast = type(self.runtime).broadcast.__get__(self.runtime)
        self.runtime.sockets['root'] = {AsyncMock()}
        message = self.db.add_message('root', 'captain', 'agent', body)
        await self.runtime.broadcast(
            'root', MessageEvent(message=MessageResponse.model_validate(message)))
        sent = list(self.runtime.sockets['root'])[0].send_json
        return message, sent.await_count

    def visible(self, message):
        return message['id'] in [m['id'] for m in self.db.message_page('root', limit=100)[0]]

    async def test_all_task_mentions_are_hidden_but_kept_for_the_task_line(self):
        await self.create()
        handle = self.db.get_attachment(self.worker.attachment_id)['name']
        message, sends = await self.say_on_root(f'@{handle} please carry on')
        self.assertEqual(sends, 0)
        self.assertFalse(self.visible(message))
        self.assertIn(message['id'], [m['id'] for m in self.db.messages_after('root', 0)])

    async def test_a_message_that_also_mentions_a_person_stays_visible(self):
        await self.create()
        handle = self.db.get_attachment(self.worker.attachment_id)['name']
        message, sends = await self.say_on_root(f'@{handle} and @greg: status?')
        self.assertEqual(sends, 1)
        self.assertTrue(self.visible(message))

    async def test_a_message_naming_no_one_or_everyone_stays_visible(self):
        await self.create()
        for body in ('plain update', '@all heads up'):
            message, sends = await self.say_on_root(body)
            self.assertEqual(sends, 1, body)
            self.assertTrue(self.visible(message), body)

    async def test_the_task_line_copy_stays_visible(self):
        await self.create()
        self.runtime.route_mentions = type(self.runtime).route_mentions.__get__(self.runtime)
        self.runtime.live[self.worker.attachment_id].deliver = AsyncMock(return_value=True)
        handle = self.db.get_attachment(self.worker.attachment_id)['name']
        message = self.db.add_message('root', 'captain', 'agent', f'@{handle} go')
        await self.runtime.route_mentions('root', message)
        shown = [m['body'] for m in self.db.message_page(self.conv_id, limit=100)[0]]
        self.assertIn(f'@{handle} go', shown)
