"""Cross-task mention notices: a delivered copy never rings, holds consolidate."""

from unittest.mock import AsyncMock

from tests.orchestrator_fixture import TaskFixture


class CrossTaskNoticeTest(TaskFixture):
    async def setUp_task(self, count=2):
        rows = [await self.create() for _ in range(count)]
        for row, name in zip(rows, ('first', 'second', 'third'), strict=False):
            self.db._exec('UPDATE conversations SET name=? WHERE id=?', (name, row['conv_id']))
        self.runtime.live['captain'].deliver = AsyncMock(return_value=True)
        self.runtime.route_mentions = type(self.runtime).route_mentions.__get__(self.runtime)
        return rows

    async def say(self, conv_id, body):
        message = self.db.add_message(conv_id, self.captain.name, 'agent', body)
        self.db._exec('UPDATE messages SET source_attachment_id=? WHERE id=?',
                      (self.captain.attachment_id, message['id']))
        message = self.db.message_by_id(conv_id, message['id'])
        await self.runtime.__class__.route_mentions(self.runtime, conv_id, message)
        return message

    def notices(self, conv_id='root'):
        return [m['body'] for m in self.db.list_messages(conv_id) if m['sender_type'] == 'system']

    def copies(self, row):
        """The captain's relayed copies to this task's implementer, not its goal tell."""
        return [m for m in self.db.list_messages(row['conv_id'])
                if m.get('audience_attachment_id') == row['implementer_id']
                and m['sender'] == self.captain.name]

    async def test_root_line_mention_delivers_to_live_task_workers_without_notices(self):
        first, second = await self.setUp_task()
        await self.say('root',
                       f"status: @{first['implementer_handle']} @{second['implementer_handle']}")
        self.assertEqual(len(self.copies(first)), 1)
        self.assertEqual(len(self.copies(second)), 1)
        self.assertEqual(self.notices(), [])

    async def test_one_consolidated_notice_lists_every_held_back_worker(self):
        first, second, third = await self.setUp_task(count=3)
        await self.say(first['conv_id'],
                       f"ping @{second['implementer_handle']} and @{third['implementer_handle']}")
        notices = [body for body in self.notices() if 'held back' in body]
        self.assertEqual(len(notices), 1)
        for row, name in ((second, 'second'), (third, 'third')):
            self.assertIn(row['implementer_handle'], notices[0])
            self.assertIn(f"«{name}»", notices[0])
            self.assertEqual(self.copies(row), [])
        self.assertIn('«first»', notices[0])
        self.assertEqual(notices[0].count('message_task'), 1)
