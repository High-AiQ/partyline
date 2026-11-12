"""accept(detach_workers=true) stops both workers of the accepted task, and only on request."""

from partyline.accept_sha import register_accept_route
from partyline.orchestrator_contracts import ReviewRequestIn, VerdictIn
from partyline.orchestrator_service import request_review, review_verdict
from tests.orchestrator_fixture import TaskFixture


class AcceptDetachWorkers(TaskFixture):
    async def approved(self):
        register_accept_route(self.app, self.runtime)
        await self.create('inspector')
        sha = self.commit()
        row = await request_review(self.runtime, self.worker, self.conv_id,
                                   ReviewRequestIn(sha=sha, what='fix', where='code'))
        await review_verdict(self.runtime, self.principal(row['reviewer_id']), self.conv_id,
                             VerdictIn(verdict='approve', findings='ok', sha=sha))
        self.actor = self.captain
        return sha, (row['implementer_id'], row['reviewer_id'])

    def status(self, ident):
        return self.db.get_attachment(ident)['status']

    async def test_accept_leaves_workers_attached_by_default(self):
        sha, workers = await self.approved()
        response = self.client.post(f'/api/conversations/{self.conv_id}/accept', json={'sha': sha})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['detached_workers'], [])
        self.assertEqual({self.status(ident) for ident in workers}, {'running'})

    async def test_accept_can_detach_both_workers_after_recording_the_sha(self):
        sha, workers = await self.approved()
        response = self.client.post(f'/api/conversations/{self.conv_id}/accept',
                                    json={'sha': sha, 'detach_workers': True})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(sorted(response.json()['detached_workers']), sorted(workers))
        self.assertEqual(self.db.get_conversation(self.conv_id)['accepted_sha'], sha)
        self.assertEqual(self.row()['status'], 'done')
        self.assertNotIn('running', {self.status(ident) for ident in workers})

    async def test_detach_workers_skips_one_that_is_already_gone(self):
        sha, workers = await self.approved()
        owner = self.db.get_attachment(workers[1])['runtime_owner']
        self.db.set_attachment_status(workers[1], 'detached', owner)
        response = self.client.post(f'/api/conversations/{self.conv_id}/accept',
                                    json={'sha': sha, 'detach_workers': True})
        self.assertEqual(response.json()['detached_workers'], [workers[0]])
