"""Express tasks: no reviewer, no review cycle, a SHA-free deliver that ends them."""

from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from partyline.db import Db
from partyline.machine_scope import allows
from partyline.mcp.tools_tasks import tool_list
from partyline.orchestrator_contracts import DeliverIn, ReopenIn, ReviewRequestIn, TaskIn
from partyline.orchestrator_express import deliver
from partyline.orchestrator_pack import LIGHT, task_pack
from partyline.orchestrator_reopen import reopen_task
from partyline.orchestrator_service import create_task, request_review
from partyline.pack_blocks import ORCHESTRATOR
from partyline.reports import list_for_parent
from partyline.return_path import ReturnPath
from tests.orchestrator_fixture import TaskFixture

DELIVERED = DeliverIn(what='mockup of the scene, see deadbeefcafe', where='/var/tmp/scene.png')


class ExpressTest(TaskFixture):
    async def express(self, **extra):
        row = await create_task(self.runtime, self.captain, 'root', TaskIn(
            name='mock', goal='Draw a mockup', implementer='builder', mode='express', **extra))
        self.conv_id = row['conv_id']
        self.worker = self.principal(row['implementer_id'])
        return row

    def captain_messages(self):
        return [m for m in self.db.message_page('root', limit=100)[0]
                if m.get('audience_attachment_id') == 'captain']

    async def test_default_mode_is_full(self):
        row = await self.create('captain')
        self.assertEqual((row['mode'], row['policy']), ('full', 'captain'))
        self.assertEqual(TaskIn(name='a', goal='b', implementer='c').mode, 'full')

    async def test_express_create_forces_policy_none_and_shows_in_listing(self):
        row = await self.express()
        self.assertEqual((row['mode'], row['policy'], row['status']), ('express', 'none', 'implementing'))
        self.assertEqual(self.row()['mode'], 'express')
        self.actor = self.human
        listed = self.client.get('/api/conversations/root/tasks').json()
        self.assertEqual([item['mode'] for item in listed], ['express'])
        self.assertEqual(self.client.get(f'/api/conversations/{self.conv_id}/task').json()['mode'],
                         'express')

    async def test_express_accepts_review_none_and_refuses_any_other_review(self):
        row = await self.express(review='none')
        self.assertEqual(row['policy'], 'none')
        for review in ('captain', 'inspector'):
            with self.assertRaises(HTTPException) as caught:
                await create_task(self.runtime, self.captain, 'root', TaskIn(
                    name=f'bad-{review}', goal='x', implementer='builder', mode='express',
                    review=review))
            self.assertEqual(caught.exception.status_code, 422)
            self.assertIn('express task has no review', caught.exception.detail)

    async def test_express_review_refused_over_http_with_422(self):
        self.actor = self.captain
        done = self.client.post('/api/conversations/root/tasks', json={
            'name': 'bad', 'goal': 'x', 'implementer': 'builder', 'mode': 'express',
            'review': 'inspector'})
        self.assertEqual(done.status_code, 422)
        self.assertEqual(self.client.post('/api/conversations/root/tasks', json={
            'name': 'bad2', 'goal': 'x', 'implementer': 'builder', 'mode': 'medium'}).status_code, 422)

    async def test_retrying_create_with_a_different_mode_conflicts(self):
        await self.express()
        with self.assertRaises(HTTPException) as caught:
            await create_task(self.runtime, self.captain, 'root', TaskIn(
                name='mock', goal='Draw a mockup', implementer='builder', review='none'))
        self.assertEqual(caught.exception.status_code, 409)

    async def test_request_review_is_refused_on_express(self):
        await self.express()
        with self.assertRaises(HTTPException) as caught:
            await request_review(self.runtime, self.worker, self.conv_id,
                                 ReviewRequestIn(sha='abcdef1', what='w', where='x'))
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(caught.exception.detail,
                         'express task: no review — report results with deliver(what, where)')
        self.actor = self.worker
        done = self.client.post(f'/api/conversations/{self.conv_id}/request-review',
                                json={'sha': 'abcdef1', 'what': 'w', 'where': 'x'})
        self.assertEqual(done.status_code, 409)
        self.assertEqual(self.row()['status'], 'implementing')

    async def test_deliver_marks_done_without_a_sha_and_notifies_the_captain(self):
        await self.express()
        row = await deliver(self.runtime, self.worker, self.conv_id, DELIVERED)
        self.assertEqual((row['status'], row['sha'], row['what'], row['location']),
                         ('done', None, DELIVERED.what, DELIVERED.where))
        reports = list_for_parent(self.db, 'root')
        self.assertEqual(len(reports), 1)
        self.assertIn('express done', reports[0]['body'])
        self.assertIn(DELIVERED.where, reports[0]['body'])
        self.assertNotIn('unverified', reports[0]['body'])
        self.assertEqual(row['report_id'], reports[0]['id'])
        self.assertTrue(any(f"report {reports[0]['id']}" in m['body'] for m in self.captain_messages()))
        self.assertEqual([m for m in self.db.message_page('root', limit=100)[0]
                          if 'not commits' in m['body']], [])
        await deliver(self.runtime, self.worker, self.conv_id, DELIVERED)
        self.assertEqual(len(list_for_parent(self.db, 'root')), 1)

    async def test_deliver_over_http_and_only_for_the_implementer_of_an_express_task(self):
        await self.express()
        self.actor = self.captain
        self.assertEqual(self.client.post(f'/api/conversations/{self.conv_id}/deliver',
                                          json={'what': 'w', 'where': 'x'}).status_code, 403)
        self.actor = self.worker
        done = self.client.post(f'/api/conversations/{self.conv_id}/deliver',
                                json={'what': 'w', 'where': 'x'})
        self.assertEqual((done.status_code, done.json()['status']), (200, 'done'))
        self.assertEqual(self.client.post(f'/api/conversations/{self.conv_id}/deliver',
                                          json={'what': 'w', 'sha': 'abcdef1', 'where': 'x'}
                                          ).status_code, 422)

    async def test_deliver_is_refused_on_a_full_task(self):
        await self.create('captain')
        with self.assertRaises(HTTPException) as caught:
            await deliver(self.runtime, self.worker, self.conv_id, DELIVERED)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertFalse(allows(self.db, self.worker, self.conv_id, 'deliver'))

    async def test_capability_and_tools_follow_the_mode(self):
        await self.express()
        self.assertTrue(allows(self.db, self.worker, self.conv_id, 'deliver'))
        names = {tool['name'] for tool in tool_list({'actions': ['deliver', 'request_review']})}
        self.assertEqual(names, {'deliver', 'request_review'})
        schema = next(tool for tool in tool_list({'actions': ['deliver']}))['inputSchema']
        self.assertEqual(set(schema['properties']), {'what', 'where'})
        create = next(tool for tool in tool_list({'actions': ['create_task']}))['inputSchema']
        self.assertEqual(create['properties']['mode']['default'], 'full')

    async def test_reopen_keeps_the_mode(self):
        await self.express()
        await deliver(self.runtime, self.worker, self.conv_id, DELIVERED)
        row = await reopen_task(self.runtime, self.captain, self.conv_id, ReopenIn(goal='again'))
        self.assertEqual((row['mode'], row['status'], row['policy']), ('express', 'implementing', 'none'))
        told = [m for m in self.db.message_page(self.conv_id, limit=100)[0] if 'reopened' in m['body']]
        self.assertIn('deliver(what, where)', told[-1]['body'])
        self.assertNotIn('request_review', told[-1]['body'])
        again = await deliver(self.runtime, self.worker, self.conv_id, DELIVERED)
        self.assertEqual(again['status'], 'done')

    async def test_pack_text_differs_by_mode(self):
        await self.express()
        express = task_pack(self.db, self.conv_id, 'implementer')
        self.assertIn('Express task: do the assignment and report results with deliver. No tests, no '
                      'test suite, no gates, no commits or review required unless the goal explicitly '
                      'asks.', express)
        self.assertNotIn('request_review', express)
        self.assertNotIn('review-', express)
        self.assertNotIn('reviewer of this task', express)
        await self.create('captain')
        full = task_pack(self.db, self.conv_id, 'implementer')
        self.assertNotIn('Express task', full)
        self.assertIn('calls request_review(sha, what, where)', full)
        self.assertLess(len(express), len(full))

    async def test_captain_pack_documents_the_choice(self):
        for text in ('mode="express"', 'its commits cannot be merged', '"light"', '"full" (default)'):
            self.assertIn(text, ORCHESTRATOR)

    async def test_mode_column_migration_is_idempotent(self):
        await self.express()
        again = Db(self.db.path)
        self.addCleanup(again.close)
        self.assertEqual(again._exec('SELECT mode FROM task_reviews').fetchone()['mode'], 'express')

    async def test_stall_reminder_and_report_name_deliver_not_request_review(self):
        await self.express()
        returns = self.runtime.returns = ReturnPath(self.runtime)
        returns.grace = 0
        async def end():
            returns.note_spoke(self.worker.attachment_id, '@captain done')
            with patch('partyline.return_path.wait_until_quiet', AsyncMock(return_value=True)):
                await returns.turn_ended(self.worker.attachment_id)
                await returns.drain()

        await end()
        found = [m for m in self.db.message_page(self.conv_id, limit=100)[0]
                 if 'no hand-off' in m['body']]
        returns.note_delivered(self.worker.attachment_id, found)
        await end()
        notices = [m['body'] for m in found]
        self.assertEqual(len(notices), 1)
        self.assertIn('deliver(what, where)', notices[0])
        self.assertNotIn('request_review', notices[0])
        row = self.row()
        self.assertEqual(row['stall_stage'], 3)
        self.assertEqual(row['findings'], 'stalled: implementer returned again without deliver '
                                          'or blocked(reason)')
        self.assertNotIn('request_review', list_for_parent(self.db, 'root')[0]['body'])


class LightTest(TaskFixture):
    async def light(self, **extra):
        row = await create_task(self.runtime, self.captain, 'root', TaskIn(
            name='small', goal='Fix a typo', implementer='builder', mode='light', **extra))
        self.conv_id = row['conv_id']
        self.worker = self.principal(row['implementer_id'])
        return row

    async def test_light_keeps_the_given_policy_and_the_review_cycle(self):
        row = await self.light(review='inspector')
        self.assertEqual((row['mode'], row['policy']), ('light', 'inspector'))
        self.assertFalse(allows(self.db, self.worker, self.conv_id, 'deliver'))
        self.assertTrue(allows(self.db, self.worker, self.conv_id, 'request_review'))
        self.assertEqual(self.db.get_conversation(self.conv_id)['task_mode'], 'light')

    async def test_light_without_review_uses_the_root_default(self):
        row = await self.light()
        self.assertEqual((row['mode'], row['policy']), ('light', 'captain'))

    async def test_light_pack_adds_only_the_gate_guidance_to_the_full_pack(self):
        await self.light()
        light = task_pack(self.db, self.conv_id, 'implementer')
        self.assertIn('Light task: gates scale with the diff', light)
        self.assertIn('partyline.task_gates', light)
        self.assertIn('request_review(sha, what, where)', light)
        self.db._exec("UPDATE task_reviews SET mode='full' WHERE conv_id=?", (self.conv_id,))
        full = task_pack(self.db, self.conv_id, 'implementer')
        self.assertNotIn('Light task', full)
        self.assertEqual(light.replace(LIGHT, ''), full)

    async def test_light_cannot_deliver_and_reopen_keeps_the_mode(self):
        await self.light(review='none')
        with self.assertRaises(HTTPException) as caught:
            await deliver(self.runtime, self.worker, self.conv_id, DELIVERED)
        self.assertEqual(caught.exception.status_code, 409)
        await request_review(self.runtime, self.worker, self.conv_id, ReviewRequestIn(
            sha=self.commit(), what='typo', where='README'))
        self.assertEqual(self.row()['status'], 'done')
        row = await reopen_task(self.runtime, self.captain, self.conv_id, ReopenIn(goal='again'))
        self.assertEqual(row['mode'], 'light')

    async def test_conversation_payload_carries_the_mode_for_every_task(self):
        await self.light()
        light = self.conv_id
        full = (await self.create('captain'))['conv_id']
        listed = {c['id']: c.get('task_mode') for c in self.db.list_conversations()}
        self.assertEqual((listed[light], listed[full], listed['root']), ('light', 'full', None))
