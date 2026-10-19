"""HTTP boundaries use live identities, and human settings default to retention."""

import sqlite3
from unittest.mock import AsyncMock, patch

from partyline.attachment_lifecycle import FreshAttachmentRequest, create_fresh_record
from partyline.conversation_routes import register_conversation_routes
from partyline.hierarchy_routes import hierarchy_router
from partyline.media import MediaStore
from partyline.orchestrator_contracts import TaskIn
from partyline.orchestrator_service import create_task
from partyline.settings_routes import settings_router
from tests.orchestrator_fixture import TaskFixture


class ApiTest(TaskFixture):
    def setUp(self):
        super().setUp()
        self.app.include_router(settings_router(self.runtime))
        self.app.include_router(hierarchy_router(self.runtime))
        register_conversation_routes(self.app, self.runtime,
                                     MediaStore(self.db, self.directory.name + '/media'),
                                     None, {}, {}, self.start)

    async def test_style_and_setting_human_only_root_only_default_captain(self):
        route = '/api/conversations/root/captain-style'
        self.actor = self.captain
        self.assertEqual(self.client.put(route, json={'captain_mode': 'orchestrator'}).status_code, 403)
        self.actor = self.human
        response = self.client.put(route, json={'captain_mode': 'orchestrator'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['default_review_policy'], 'captain')
        setting = '/api/settings/auto_clean_task_history'
        self.assertEqual(self.client.get(setting).json(), {'enabled': False})
        self.assertEqual(self.client.put(setting, json={'enabled': True}).json(), {'enabled': True})
        self.assertEqual(self.db.get_setting('auto_clean_task_history'), 'true')
        self.actor = self.captain
        self.assertEqual(self.client.put(setting, json={'enabled': False}).status_code, 403)
        self.assertEqual(self.client.get(setting).status_code, 403)
        row = await self.create()
        self.actor = self.human
        self.assertEqual(self.client.put('/api/conversations/' + row['conv_id'] + '/captain-style',
                                         json={'captain_mode': 'orchestrator'}).status_code, 409)
        self.assertEqual(self.client.put(route, json={'captain_mode': 'manager_tree'}).status_code, 409)
        self.assertEqual(self.client.put(route, json={'captain_mode': 'orchestrator',
                                                      'default_review_policy': 'missing'}).status_code, 400)

    async def test_task_endpoints_authorized_for_exact_implementer_and_reviewer(self):
        self.actor = self.captain
        response = self.client.post('/api/conversations/root/tasks', json={
            'name': 'http slice', 'goal': 'test HTTP', 'implementer': 'builder', 'review': 'inspector'})
        self.assertEqual(response.status_code, 201, response.text)
        row = response.json()
        self.assertEqual(self.client.get('/api/conversations/root/tasks').json(), [row])
        conv = row['conv_id']
        self.conv_id = conv
        worker = self.principal(row['implementer_id'])
        self.assertEqual(self.client.get(f'/api/conversations/{conv}/task').json(), row)
        self.assertEqual(self.client.get('/api/conversations/root/task').status_code, 404)
        request = f'/api/conversations/{conv}/request-review'
        data = {'what': 'feature', 'where': 'code'}
        self.assertEqual(self.client.post(request, json=data).status_code, 403)
        self.actor = worker
        self.assertEqual(self.client.get('/api/conversations/root/tasks').status_code, 403)
        response = self.client.post(request, json=data)
        self.assertEqual(response.status_code, 200, response.text)
        verdict = f'/api/conversations/{conv}/review-verdict'
        data = {'verdict': 'approve', 'findings': 'verified'}
        self.assertEqual(self.client.post(verdict, json=data).status_code, 403)
        self.actor = self.principal(response.json()['reviewer_id'])
        self.assertEqual(self.client.post(verdict, json=data).json()['status'], 'approved')

    async def test_retention_overrides_root_force_discard_and_shared_branch_override(self):
        row = await self.create()
        conv = row['conv_id']
        self.actor = self.captain
        response = self.client.delete(f'/api/conversations/{conv}?force_discard=true&stop_processes=true')
        self.assertEqual(response.status_code, 403, response.text)
        response = self.client.post(f'/api/conversations/{conv}/attachments', json={
            'name': 'extra', 'adapter': 'fake', 'command': 'fake', 'allow_shared_branch': True})
        self.assertEqual(response.status_code, 403)
        self.actor = self.human
        response = self.client.post(f'/api/conversations/{conv}/attachments', json={
            'name': 'extra', 'adapter': 'fake', 'command': 'fake', 'allow_shared_branch': True})
        self.assertEqual(response.status_code, 409)
        response = self.client.post(f'/api/conversations/{conv}/children', json={'name': 'nested'})
        self.assertEqual(response.status_code, 409)
        response = self.client.post('/api/conversations/root/children', json={'name': 'unmanaged'})
        self.assertEqual(response.status_code, 409)
        with self.assertRaises(Exception) as refused:
            await create_fresh_record(self.db, self.db.get_attachment(row['implementer_id']),
                                      FreshAttachmentRequest())
        self.assertEqual(refused.exception.status_code, 409)

    async def test_implementer_spawn_refusal_is_loud(self):
        self.actor = self.captain
        with patch('partyline.orchestrator_service.spawn', AsyncMock(side_effect=ValueError('missing CLI'))):
            with self.assertRaises(ValueError):
                await create_task(self.runtime, self.captain, 'root', TaskIn(
                    name='failed', goal='goal', implementer='builder'))
        pending = self.db._exec('SELECT conv_id FROM task_reviews').fetchone()['conv_id']
        result = await create_task(self.runtime, self.captain, 'root', TaskIn(
            name='failed', goal='goal', implementer='builder'))
        self.assertEqual(result['conv_id'], pending)
        self.assertEqual(len(self.db.list_attachments(pending)), 1)
        root_messages, _ = self.db.message_page('root', limit=100)
        self.assertTrue(any('missing CLI' in m['body'] for m in root_messages))

    async def test_reparenting_cannot_bypass_root_only_mode_or_task_parent(self):
        self.db.create_conversation('other', 'Other')
        self.actor = self.human
        response = self.client.put('/api/conversations/other/parent', json={'parent_id': 'root'})
        self.assertEqual(response.status_code, 409)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db._exec("UPDATE conversations SET parent_id='other' WHERE id='root'")


    async def test_accept_requires_exact_full_approved_sha(self):
        from partyline.accept_sha import register_accept_route
        from partyline.orchestrator_contracts import ReviewRequestIn
        from partyline.orchestrator_service import request_review
        register_accept_route(self.app, self.runtime)
        await self.create('none')
        sha = self.commit()
        await request_review(self.runtime, self.worker, self.conv_id,
                             ReviewRequestIn(sha=sha, what='done', where='code'))
        self.actor = self.captain
        endpoint = f'/api/conversations/{self.conv_id}/accept'
        for candidate in ('', sha[:1], sha[:4], sha[:39], '0' * 40):
            with self.subTest(candidate=candidate):
                response = self.client.post(endpoint, json={'sha': candidate})
                self.assertIn(response.status_code, (409, 422), response.text)
        response = self.client.post(endpoint, json={'sha': sha})
        self.assertEqual(response.status_code, 200, response.text)

    async def test_line_metadata_tracks_status_round_and_assigned_names(self):
        from partyline.orchestrator_contracts import ReviewRequestIn, VerdictIn
        from partyline.orchestrator_service import request_review, review_verdict
        row = await self.create()
        line = self.db.get_conversation(self.conv_id)
        self.assertEqual(line['task_status'], 'implementing')
        self.assertEqual(line['task_root_name'], 'Root')
        self.assertEqual(line['task_implementer_name'], 'builder')
        await request_review(self.runtime, self.worker, self.conv_id,
                             ReviewRequestIn(what='feature', where='code'))
        row = self.row()
        await review_verdict(self.runtime, self.principal(row['reviewer_id']), self.conv_id,
                             VerdictIn(verdict='approve', findings='verified'))
        line = next(c for c in self.db.list_conversations() if c['id'] == self.conv_id)
        self.assertEqual(line['task_status'], 'approved')
        self.assertEqual(line['task_round'], 1)
        self.assertEqual(line['task_reviewer_name'], self.db.get_attachment(row['reviewer_id'])['name'])
        self.assertEqual(line['live_count'], 2)
        await self.create('captain')
        self.assertEqual(self.db.get_conversation(self.conv_id)['task_reviewer_name'], 'captain')
        await self.create('none')
        self.assertEqual(self.db.get_conversation(self.conv_id)['task_reviewer_name'], 'none')
