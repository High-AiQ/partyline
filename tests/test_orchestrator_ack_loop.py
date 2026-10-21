"""A task worker and its root captain cannot acknowledge each other forever."""

from unittest.mock import AsyncMock

from partyline.task_ack_limit import withheld_ack
from tests.orchestrator_fixture import TaskFixture


class AckLoopTest(TaskFixture):
    async def speak(self, line, sender, body):
        message = self.db.add_message(line, sender, 'agent', body)
        await self.runtime.__class__.route_mentions(self.runtime, line, message)
        return message

    async def test_bare_acks_between_worker_and_root_captain_stop_crossing_lines(self):
        await self.create()
        self.runtime.route_mentions = type(self.runtime).route_mentions.__get__(self.runtime)
        for att in ('captain', self.worker.attachment_id):
            self.runtime.live[att].deliver = AsyncMock(return_value=True)
        handle = self.db.get_attachment(self.worker.attachment_id)['name']
        for _ in range(10):
            await self.speak(self.conv_id, handle, 'ack @captain')
            await self.speak('root', 'captain', f'ack @{handle}')
        copies = [m for line in ('root', self.conv_id) for m in self.db.messages_after(line, 0)
                  if m['sender_type'] == 'agent' and m['audience_attachment_id']]
        self.assertEqual(len(copies), 2)  # two bare acks cross, the rest are stored only
        notices = [m for m in self.db.messages_after(self.conv_id, 0)
                   if 'acknowledgment not relayed' in m['body']]
        self.assertTrue(notices)
        self.assertEqual(notices[0]['audience_attachment_id'], self.worker.attachment_id)

    async def test_a_question_a_sha_or_a_report_still_crosses(self):
        await self.create()
        self.runtime.route_mentions = type(self.runtime).route_mentions.__get__(self.runtime)
        for att in ('captain', self.worker.attachment_id):
            self.runtime.live[att].deliver = AsyncMock(return_value=True)
        handle = self.db.get_attachment(self.worker.attachment_id)['name']
        for _ in range(3):
            await self.speak(self.conv_id, handle, 'ack @captain')
        for body in ('which repo? @captain', 'built abc1234def @captain'):
            before = len(self.db.messages_after('root', 0))
            await self.speak(self.conv_id, handle, body)
            self.assertEqual(len(self.db.messages_after('root', 0)), before + 1, body)

    async def test_people_and_other_lines_are_not_limited(self):
        await self.create()
        self.assertFalse(withheld_ack(self.db, 'root', 'elsewhere', {'id': 99, 'body': 'ok'}))
