"""A captain's rework message protects the SHA currently under review."""

from unittest.mock import patch

from fastapi import HTTPException

from partyline.mcp.captain_schemas import schema as captain_schema
from partyline.mcp.tools_captain import tool_list as captain_tool_list
from partyline.mcp.tools_tasks import tool_list
from partyline.orchestrator_contracts import MessageTaskIn, ReviewRequestIn, VerdictIn
from partyline.orchestrator_handles import message_task
from partyline.orchestrator_service import request_review, review_verdict
from partyline.orchestrator_store import tasks
from tests.orchestrator_fixture import TaskFixture


class ReviewHoldTest(TaskFixture):
    def setUp(self):
        super().setUp()
        # Every wall clock used by task setup and transitions is fixed in these tests.
        clock = patch('time.time', return_value=1_800_000_000.0)
        clock.start()
        self.addCleanup(clock.stop)

    async def in_review(self):
        await self.create()
        sha = self.commit()
        row = await request_review(self.runtime, self.worker, self.conv_id,
                                   ReviewRequestIn(sha=sha, what='feature', where='code'))
        return row, sha, self.principal(row['reviewer_id'])

    def private_messages(self):
        return self.db.message_page(self.conv_id, limit=100)[0]

    async def test_message_holds_sha_refuses_approval_but_allows_changes_and_new_delivery(self):
        row, sha, reviewer = await self.in_review()
        held = await message_task(self.runtime, self.human, self.conv_id,
                                  MessageTaskIn(text='Please rework the edge case'))
        self.assertEqual(held['review_hold_sha'], sha)
        self.assertEqual(held['review_hold'], f'review held: captain changes after {sha[:7]}')
        listed = next(item for item in tasks(self.db, 'root', visibility=True)
                      if item['conv_id'] == self.conv_id)
        self.assertEqual(listed['review_hold'], held['review_hold'])
        notice = [message for message in self.private_messages()
                  if 'hold your verdict until the implementer re-delivers' in message['body']][-1]
        self.assertEqual(notice['audience_attachment_id'], reviewer.attachment_id)

        with self.assertRaises(HTTPException) as caught:
            await review_verdict(self.runtime, reviewer, self.conv_id,
                                 VerdictIn(verdict='approve', sha=sha, findings='looks good'))
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn(sha[:7], caught.exception.detail)
        self.assertEqual(self.row()['status'], 'in_review')

        changes = await review_verdict(self.runtime, reviewer, self.conv_id,
                                       VerdictIn(verdict='changes', sha=sha, findings='fix edge'))
        self.assertEqual(changes['status'], 'implementing')
        new_sha = self.commit('reworked')
        delivered = await request_review(self.runtime, self.worker, self.conv_id,
                                         ReviewRequestIn(sha=new_sha, what='feature', where='code'))
        self.assertIsNone(delivered['review_hold_sha'])
        self.assertIsNone(delivered['review_hold'])

    async def test_explicit_release_clears_hold_and_approval_can_proceed(self):
        _, sha, reviewer = await self.in_review()
        await message_task(self.runtime, self.captain, self.conv_id, MessageTaskIn(text='Rework'))
        self.actor = self.captain
        response = self.client.post(f'/api/conversations/{self.conv_id}/task/review-hold',
                                    json={'hold': False})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()['review_hold'])
        release_notice = [message for message in self.private_messages()
                          if 'Captain released the review hold' in message['body']][-1]
        self.assertEqual(release_notice['audience_attachment_id'], reviewer.attachment_id)
        approved = await review_verdict(self.runtime, reviewer, self.conv_id,
                                        VerdictIn(verdict='approve', sha=sha, findings='verified'))
        self.assertEqual(approved['status'], 'approved')

    async def test_new_sha_delivery_during_review_clears_hold(self):
        _, _, _ = await self.in_review()
        await message_task(self.runtime, self.captain, self.conv_id, MessageTaskIn(text='Rework'))
        new_sha = self.commit('reworked')
        delivered = await request_review(self.runtime, self.worker, self.conv_id,
                                         ReviewRequestIn(sha=new_sha, what='feature', where='code'))
        self.assertEqual(delivered['status'], 'in_review')
        self.assertEqual(delivered['sha'], new_sha)
        self.assertIsNone(delivered['review_hold_sha'])

    async def test_same_sha_redelivery_after_changes_keeps_hold(self):
        row, sha, reviewer = await self.in_review()
        await message_task(self.runtime, self.captain, self.conv_id, MessageTaskIn(text='Rework'))
        await review_verdict(self.runtime, reviewer, self.conv_id,
                             VerdictIn(verdict='changes', sha=sha, findings='please rework'))
        redelivered = await request_review(self.runtime, self.worker, self.conv_id,
                                           ReviewRequestIn(sha=sha, what='feature', where='code'))
        self.assertEqual(redelivered['sha'], row['sha'])
        self.assertEqual(redelivered['review_hold_sha'], sha)
        with self.assertRaises(HTTPException) as caught:
            await review_verdict(self.runtime, reviewer, self.conv_id,
                                 VerdictIn(verdict='approve', sha=sha, findings='looks good'))
        self.assertEqual(caught.exception.status_code, 409)

    async def test_opt_out_and_outside_review_do_not_hold(self):
        await self.create()
        outside = await message_task(self.runtime, self.captain, self.conv_id,
                                     MessageTaskIn(text='Before review'))
        self.assertIsNone(outside['review_hold_sha'])
        row, _, _ = await self.in_review()
        opted_out = await message_task(self.runtime, self.captain, self.conv_id,
                                       MessageTaskIn(text='FYI, no change needed', hold_review=False))
        self.assertIsNone(opted_out['review_hold_sha'])
        self.assertIsNone(opted_out['review_hold'])
        board = tasks(self.db, 'root', visibility=True)
        listed = next(item for item in board if item['conv_id'] == row['conv_id'])
        self.assertIsNone(listed['review_hold'])

    async def test_mcp_schemas_describe_the_opt_out_and_release(self):
        tools = tool_list({'actions': ['message_task']})
        message = next(tool for tool in tools if tool['name'] == 'message_task')
        self.assertEqual(message['inputSchema']['properties']['hold_review']['type'], 'boolean')
        self.assertIn('hold_review=false', message['description'])
        self.assertEqual(captain_schema('review_hold')['properties']['hold']['type'], 'boolean')
        captain = next(tool for tool in captain_tool_list(
            {'kind': 'machine', 'role': 'lead', 'is_lead': True, 'actions': ['assign']})
                       if tool['name'] == 'review_hold')
        self.assertIn('hold=false', captain['description'])

