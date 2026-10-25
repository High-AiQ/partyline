"""Task routes accept a task's tag, handle or line name in place of its line id."""

from partyline.auth_guard import Principal
from partyline.orchestrator_handles import task_line
from partyline.orchestrator_store import task
from tests.orchestrator_fixture import TaskFixture


class TaskRefTest(TaskFixture):
    async def test_message_route_accepts_handle_tag_and_line_name(self):
        row = await self.create()
        self.actor = self.captain
        line_name = self.db.get_conversation(self.conv_id)['name']
        for ref in (row['implementer_handle'], row['tag'], line_name):
            response = self.client.post(f'/api/conversations/{ref}/task/message',
                                        json={'text': f'by {ref}'})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['conv_id'], self.conv_id)

    async def test_unknown_names_stay_404(self):
        await self.create()
        self.actor = self.captain
        self.assertEqual(task_line(self.db, self.captain, 'impl-nope00'), 'impl-nope00')
        self.assertEqual(self.client.post('/api/conversations/impl-nope00/task/message',
                                          json={'text': 'x'}).status_code, 404)

    async def test_a_name_shared_by_two_tasks_is_refused_with_409(self):
        await self.create()
        second = await self.create()
        self.actor = self.captain
        response = self.client.post('/api/conversations/slice/task/message', json={'text': 'x'})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn('matches 2 tasks', response.text)
        self.assertEqual(task_line(self.db, self.captain, second['tag']), second['conv_id'])

    async def test_a_person_resolves_names_across_every_task(self):
        row = await self.create()
        person = Principal(kind='user', name='human')
        self.assertEqual(task_line(self.db, person, row['tag']), self.conv_id)
        self.assertEqual(task_line(self.db, person, self.conv_id), self.conv_id)
        self.assertIsNotNone(task(self.db, self.conv_id))
        other = Principal(kind='machine', name='x', conv_id='elsewhere', attachment_id='x')
        self.assertEqual(task_line(self.db, other, row['tag']), row['tag'])

    async def test_restart_and_resume_routes_take_names(self):
        row = await self.create()
        self.actor = self.captain
        self.db._exec("UPDATE attachments SET status='exited' WHERE id=?", (row['implementer_id'],))
        response = self.client.post(f'/api/conversations/{row["implementer_handle"]}/task/implementer')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['conv_id'], self.conv_id)
