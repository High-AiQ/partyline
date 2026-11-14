"""Write replies about a task or report are short status objects; the full records stay on the reads.

A reply to a write tool names the line, its status, round and SHA, and the field the caller
changed. It never echoes the goal, findings, report body or workspace detail, which run to
thousands of characters on every reply. `tasks(conv_id)`, `goal` and `reports get` still return them.
"""

from partyline.goal import register_goal_route
from partyline.hierarchy_routes import hierarchy_router
from tests.orchestrator_fixture import TaskFixture

LONG_GOAL = 'Build the feature in full detail. ' * 180      # about 5,200 characters
LONG_TEXT = 'Detailed finding with evidence. ' * 40         # about 1,160 characters
REPLY_BOUND = 1200  # bytes: a status object is about 900; the long prose alone is 5 times that
PROSE_KEYS = ('goal', 'findings', 'previous_findings', 'what', 'location', 'workspaces',
              'wait_reason', 'body', 'review_worktree', 'created_at', 'reviewer_restarts')


class TaskReplyShapeTest(TaskFixture):
    def setUp(self):
        super().setUp()
        self.app.include_router(hierarchy_router(self.runtime))
        register_goal_route(self.app, self.runtime)

    def assertStatus(self, response, code=200):
        self.assertEqual(response.status_code, code, response.text)
        self.assertLess(len(response.content), REPLY_BOUND, response.text)
        body = response.json()
        for key in PROSE_KEYS:
            self.assertNotIn(key, body)
        self.assertNotIn(LONG_GOAL.strip(), response.text)
        self.assertNotIn(LONG_TEXT.strip(), response.text)
        return body

    async def test_every_task_write_replies_with_a_status(self):
        self.actor = self.captain
        created = self.client.post('/api/conversations/root/tasks', json={
            'name': 'long slice', 'goal': LONG_GOAL, 'implementer': 'builder', 'review': 'inspector'})
        body = self.assertStatus(created, 201)
        self.assertEqual(body['status'], 'implementing')
        self.assertTrue(body['repositories'])
        self.conv_id = body['conv_id']
        self.worker = self.principal(body['implementer_id'])
        task_route = f'/api/conversations/{self.conv_id}'

        self.actor = self.worker
        blocked = self.client.post(f'{task_route}/blocked', json={'reason': LONG_TEXT})
        self.assertEqual(self.assertStatus(blocked)['status'], 'blocked')
        resumed = self.client.post(f'{task_route}/task/resume', json={'note': 'carrying on'})
        self.assertEqual(self.assertStatus(resumed)['status'], 'implementing')
        sha = self.commit()
        requested = self.client.post(f'{task_route}/request-review',
                                     json={'sha': sha, 'what': 'feature', 'where': 'code'})
        body = self.assertStatus(requested)
        self.assertEqual((body['status'], body['sha']), ('in_review', sha))

        reviewer = self.principal(body['reviewer_id'])
        self.actor = reviewer
        changes = self.client.post(f'{task_route}/review-verdict', json={
            'verdict': 'changes', 'sha': sha, 'findings': LONG_TEXT})
        self.assertEqual(self.assertStatus(changes)['status'], 'implementing')
        self.assertEqual(self.client.get(f'{task_route}/task').json()['findings'], LONG_TEXT)

        self.actor = self.captain
        message = self.client.post(f'{task_route}/task/message', json={'text': 'keep going'})
        self.assertStatus(message)
        retargeted = self.client.post(f'{task_route}/task/goal', json={'goal': LONG_GOAL})
        body = self.assertStatus(retargeted)
        self.assertEqual(body['goal_chars'], len(LONG_GOAL.strip()))

        approved_sha = self.commit('approved')
        self.actor = self.worker
        self.assertEqual(self.assertStatus(self.client.post(
            f'{task_route}/request-review', json={'sha': approved_sha, 'what': 'fix', 'where': 'code'})
        )['status'], 'in_review')
        self.actor = reviewer
        approved = self.client.post(f'{task_route}/review-verdict', json={
            'verdict': 'approve', 'sha': approved_sha, 'findings': 'verified'})
        self.assertEqual(self.assertStatus(approved)['status'], 'approved')
        self.actor = self.captain
        reopened = self.client.post(f'{task_route}/task/reopen', json={'goal': LONG_GOAL})
        body = self.assertStatus(reopened)
        self.assertEqual((body['status'], body['round']), ('implementing', 0))
        self.assertEqual(body['goal_chars'], len(LONG_GOAL.strip()))

    async def test_reads_still_return_the_full_record(self):
        self.actor = self.captain
        body = self.client.post('/api/conversations/root/tasks', json={
            'name': 'long slice', 'goal': LONG_GOAL, 'implementer': 'builder', 'review': 'inspector'}
        ).json()
        self.conv_id = body['conv_id']
        detail = self.client.get(f'/api/conversations/{self.conv_id}/task').json()
        self.assertEqual(detail['goal'].strip(), LONG_GOAL.strip())
        listing = self.client.get('/api/conversations/root/tasks').json()
        self.assertEqual(listing[0]['goal'].strip(), LONG_GOAL.strip())
        self.assertIn('created_at', detail)

    async def test_report_post_and_ack_reply_with_an_id_and_revision(self):
        await self.create()
        self.actor = self.human  # a line's implementer cannot post a report; a person can
        posted = self.client.post(f'/api/conversations/{self.conv_id}/reports',
                                  json={'body': LONG_TEXT, 'notify': False})
        body = self.assertStatus(posted, 201)
        report_id = body['id']
        self.assertEqual(body['parent_conv_id'], 'root')
        self.assertEqual(body['child_conv_id'], self.conv_id)
        self.assertEqual(body['revision'], 1)

        self.actor = self.captain
        acked = self.client.post(f'/api/conversations/root/reports/{report_id}/ack', json={'revision': 1})
        body = self.assertStatus(acked)
        self.assertEqual((body['id'], body['revision']), (report_id, 1))
        self.assertIsNotNone(body['acknowledged_at'])

        read = self.client.get(f'/api/conversations/root/reports/{report_id}')
        self.assertEqual(read.status_code, 200, read.text)
        self.assertEqual(read.json()['body'], LONG_TEXT.strip())

    async def test_express_delivery_replies_with_a_status(self):
        self.actor = self.captain
        body = self.client.post('/api/conversations/root/tasks', json={
            'name': 'express slice', 'goal': LONG_GOAL, 'implementer': 'builder', 'mode': 'express'}).json()
        self.actor = self.principal(body['implementer_id'])
        delivered = self.client.post(f"/api/conversations/{body['conv_id']}/deliver",
                                     json={'what': LONG_TEXT.strip()[:900], 'where': 'out/'})
        self.assertEqual(self.assertStatus(delivered)['status'], 'done')

    async def test_restart_routes_reply_with_a_status(self):
        self.actor = self.captain
        body = self.client.post('/api/conversations/root/tasks', json={
            'name': 'restart slice', 'goal': LONG_GOAL, 'implementer': 'builder',
            'review': 'inspector'}).json()
        self.conv_id = body['conv_id']
        route = f"/api/conversations/{body['conv_id']}"
        self.db._exec("UPDATE attachments SET status='exited' WHERE id=?", (body['implementer_id'],))
        restarted = self.client.post(f'{route}/task/implementer')
        self.assertEqual(self.assertStatus(restarted)['status'], 'implementing')

        self.actor = self.principal(body['implementer_id'])
        requested = self.client.post(f'{route}/request-review',
                                     json={'sha': self.commit(), 'what': 'feature', 'where': 'code'})
        reviewer_id = self.assertStatus(requested)['reviewer_id']
        self.db._exec("UPDATE attachments SET status='exited' WHERE id=?", (reviewer_id,))
        self.actor = self.captain
        restarted = self.client.post(f'{route}/task/reviewer')
        self.assertEqual(self.assertStatus(restarted)['status'], 'in_review')

    async def test_reviewer_and_wait_routes_reply_with_a_status(self):
        self.actor = self.captain
        body = self.client.post('/api/conversations/root/tasks', json={
            'name': 'review slice', 'goal': LONG_GOAL, 'implementer': 'builder',
            'review': 'inspector'}).json()
        self.conv_id = body['conv_id']
        route = f"/api/conversations/{body['conv_id']}"
        self.actor = self.principal(body['implementer_id'])
        requested = self.client.post(f'{route}/request-review',
                                     json={'sha': self.commit(), 'what': 'feature', 'where': 'code'})
        reviewer = self.principal(self.assertStatus(requested)['reviewer_id'])
        self.actor = self.principal(body['implementer_id'])
        nudged = self.client.post(f'{route}/task/nudge-reviewer', json={})
        self.assertEqual(self.assertStatus(nudged)['status'], 'in_review')
        self.actor = reviewer
        gap = self.client.post(f'{route}/env-gap', json={
            'repository': self.repo, 'what_failed': LONG_TEXT.strip()[:900], 'tried': 'the suite'})
        self.assertStatus(gap)
        waiting = self.client.post(f'{route}/waiting', \
                                            json={'reason': LONG_TEXT.strip()[:900], 'seconds': 60})
        self.assertTrue(self.assertStatus(waiting)['wait_until'])

    async def test_a_line_goal_write_replies_with_the_length_only(self):
        self.actor = self.captain
        line_goal = 'Line goal detail. ' * 140  # about 2,800 characters, under the 3,000 line cap
        put = self.client.put('/api/conversations/root/goal', json={'goal': line_goal})
        body = self.assertStatus(put)
        self.assertEqual((body['id'], body['goal_chars']), ('root', len(line_goal.strip())))
        self.assertEqual(self.db.get_conversation('root')['goal'], line_goal.strip())

    async def test_create_child_replies_with_the_line_status(self):
        self.actor = self.captain
        child_goal = 'Child line goal detail. ' * 100  # about 2,300 characters, under the line cap
        created = self.client.post('/api/conversations/root/children', json={
            'name': 'status child', 'goal': child_goal})
        body = self.assertStatus(created, 201)
        child = body['conversation']
        self.assertNotIn('goal', child)
        self.assertNotIn('topic', child)
        self.assertEqual((child['name'], child['parent_id'], child['goal_chars']),
                         ('status child', 'root', len(child_goal.strip())))
        self.assertEqual(self.db.get_conversation(child['id'])['goal'], child_goal.strip())
