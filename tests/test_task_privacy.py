"""A root captain's message is hidden only when it opens by addressing task processes."""

from partyline.orchestrator_schema import MIGRATIONS
from partyline.task_privacy import is_task_only
from tests.orchestrator_fixture import TaskFixture


class TaskPrivacyTest(TaskFixture):
    async def setUp_names(self):
        await self.create()
        self.db._exec("UPDATE attachments SET name='impl-abc123' WHERE id=?", (self.worker.attachment_id,))

    def said(self, body):
        message = self.db.add_message('root', 'captain', 'agent', body)
        return message, is_task_only(self.db, 'root', message)

    async def test_opening_mention_of_task_processes_is_hidden(self):
        await self.setUp_names()
        self.assertTrue(self.said('@impl-abc123 please rebase')[1])
        self.assertTrue(self.said('  @impl-abc123, @impl-abc123 rebase both')[1])

    async def test_prose_for_a_person_naming_a_handle_stays_visible(self):
        await self.setUp_names()
        self.assertFalse(self.said('Greg, the reader passed review. @impl-abc123')[1])
        self.assertFalse(self.said('done. @impl-abc123')[1])
        self.assertFalse(self.said('nothing to mention')[1])

    async def test_other_exemptions_hold(self):
        await self.setUp_names()
        self.assertFalse(self.said('@impl-abc123 and @greg look')[1])
        self.assertFalse(self.said('@all @impl-abc123 look')[1])

    async def test_migration_unhides_lead_prose_and_keeps_relay_copies(self):
        await self.setUp_names()
        lead, _ = self.said('Greg, it passed. @impl-abc123')
        opening, _ = self.said('@impl-abc123 rebase')
        relay = self.db.add_message('root', 'captain', 'agent', 'Greg, relay')
        stamped = self.db.add_message('root', 'captain', 'agent', 'Greg, stamped')
        task = self.db.add_message('root', 'impl-abc123', 'agent', 'plain from task')
        self.db._exec("UPDATE messages SET task_private=1,audience_attachment_id='captain'"
                      " WHERE id=?", (relay['id'],))
        self.db._exec("UPDATE messages SET task_private=1,source_attachment_id='captain'"
                      " WHERE id=?", (stamped['id'],))
        for row in (lead, opening, task):
            self.db._exec("UPDATE messages SET task_private=1 WHERE id=?", (row['id'],))

        unhide = next(m for m in MIGRATIONS if m.startswith('UPDATE messages SET task_private=0'))

        def hidden():
            return {r['id'] for r in self.db._exec('SELECT id FROM messages WHERE task_private=1')}

        for _ in range(2):  # the second pass changes nothing
            self.db._exec(unhide)
            self.assertEqual(hidden(), {opening['id'], relay['id'], task['id']})
