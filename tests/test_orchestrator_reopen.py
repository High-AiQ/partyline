"""An approved or done task is reopened for new work, never silently messaged."""

from unittest.mock import Mock

from fastapi import HTTPException

from partyline.machine_scope import allows
from partyline.mcp.tools_tasks import call, tool_list
from partyline.orchestrator_contracts import ReopenIn, ReviewRequestIn, VerdictIn
from partyline.orchestrator_pack import task_pack
from partyline.orchestrator_reopen import reopen_task, unreopened
from partyline.orchestrator_service import request_review, review_verdict
from partyline.pack_blocks import ORCHESTRATOR
from partyline.orchestrator_stall import began
from tests.orchestrator_fixture import TaskFixture


class ReopenTest(TaskFixture):
    def messages(self, conv):
        return self.db.message_page(conv, limit=100)[0]

    async def settle(self, policy='captain'):
        await self.create(policy)
        await request_review(self.runtime, self.worker, self.conv_id,
                             ReviewRequestIn(sha=self.commit(), what='built', where='code'))
        if policy == 'captain':
            await review_verdict(self.runtime, self.captain, self.conv_id,
                                 VerdictIn(verdict='approve', findings='fine'))
        return self.row()

    def say(self, body, root=True):
        message = self.db.add_message(self.conv_id, 'captain' if root else 'peer', 'agent', body)
        if root:
            self.db._exec('UPDATE messages SET source_conv_id=? WHERE id=?', ('root', message['id']))
        return message

    def notices(self):
        return [m for m in self.messages('root') if 'working again' in m['body']]

    async def reopen(self, actor, goal='second job'):
        return await reopen_task(self.runtime, actor, self.conv_id, ReopenIn(goal=goal))

    async def test_reopen_from_approved_resets_the_cycle_and_keeps_history(self):
        approved = await self.settle()
        self.assertEqual(approved['status'], 'approved')
        self.db._exec('UPDATE task_reviews SET round=3,merged=1 WHERE conv_id=?', (self.conv_id,))
        self.db._exec("UPDATE conversations SET accepted_sha='abc' WHERE id=?", (self.conv_id,))
        from partyline.reports import list_for_parent
        reports = len(list_for_parent(self.db, 'root'))
        row = await self.reopen(self.captain)
        self.assertEqual(row['status'], 'implementing')
        self.assertEqual((row['round'], row['sha'], row['what'], row['findings'], row['report_id']),
                         (0, None, '', '', None))
        self.assertEqual((row['stall_stage'], row['blocked_at'], row['reopen_noticed']), (0, None, 0))
        self.assertEqual(self.db.get_conversation(self.conv_id)['goal'], 'second job')
        self.assertEqual(self.db.get_conversation(self.conv_id)['accepted_sha'], 'abc')
        self.assertEqual(self.row()['merged'], 1)
        self.assertEqual(len(list_for_parent(self.db, 'root')), reports)
        brief = [m for m in self.messages(self.conv_id) if 'second job' in m['body']]
        self.assertEqual(brief[-1]['audience_attachment_id'], self.worker.attachment_id)
        again = await request_review(self.runtime, self.worker, self.conv_id,
                                     ReviewRequestIn(sha=self.commit('two'), what='b', where='c'))
        self.assertEqual((again['status'], again['round']), ('in_review', 1))

    async def test_reopen_from_done_and_a_person_may_reopen(self):
        self.assertEqual((await self.settle('none'))['status'], 'done')
        self.assertEqual((await self.reopen(self.human))['status'], 'implementing')

    async def test_other_states_are_refused_with_409(self):
        await self.create('captain')
        for _ in range(2):
            with self.assertRaises(HTTPException) as caught:
                await self.reopen(self.captain)
            self.assertEqual(caught.exception.status_code, 409)
            if _ == 0:
                await request_review(self.runtime, self.worker, self.conv_id,
                                     ReviewRequestIn(sha=self.commit(), what='b', where='c'))
        with self.assertRaises(HTTPException) as caught:
            await reopen_task(self.runtime, self.captain, 'nope', ReopenIn(goal='x'))
        self.assertEqual(caught.exception.status_code, 404)

    async def test_implementer_and_other_machines_are_refused(self):
        await self.settle()
        self.db.create_conversation('other', 'Other')
        self.db.add_attachment('rival', 'other', 'rival', 'fake', ['fake'], self.repo, 'owner')
        self.db._exec("UPDATE attachments SET is_lead=1,status='running' WHERE id='rival'")
        url = f'/api/conversations/{self.conv_id}/task/reopen'
        for actor, expected in ((self.worker, 403), (self.principal('rival'), 403),
                                (self.captain, 200)):
            self.actor = actor
            self.assertEqual(self.client.post(url, json={'goal': 'again'}).status_code, expected)
        self.actor = self.human
        self.assertEqual(self.client.post(url, json={'goal': ' '}).status_code, 422)
        self.assertFalse(allows(self.db, self.worker, self.conv_id, 'reopen_task'))

    async def test_mcp_tool_is_root_only_and_names_the_task(self):
        self.assertEqual([t['name'] for t in tool_list({'actions': ['reopen_task']})], ['reopen_task'])
        schema = tool_list({'actions': ['reopen_task']})[0]['inputSchema']
        self.assertEqual(sorted(schema['required']), ['conv_id', 'goal'])
        client = Mock(home='root')
        call(client, 'reopen_task', {'conv_id': 'task', 'goal': 'g'}, {'actions': ['reopen_task']})
        client.request.assert_called_once_with('POST', '/api/conversations/task/task/reopen', {'goal': 'g'})
        await self.create()
        self.assertTrue(allows(self.db, self.captain, 'root', 'reopen_task'))

    async def test_detached_implementer_is_woken_with_its_session(self):
        await self.settle()
        ident = self.worker.attachment_id
        self.db._exec("UPDATE attachments SET status='exited',cli_session='s' WHERE id=?", (ident,))
        self.runtime.live.pop(ident, None)
        await self.reopen(self.captain)
        self.assertEqual(self.db.get_attachment(ident)['status'], 'running')

    async def test_safety_net_notifies_the_root_once_and_does_not_reopen(self):
        await self.settle()
        att = self.db.get_attachment(self.worker.attachment_id)
        await began(self.runtime, att)
        self.assertEqual(self.notices(), [])
        self.say('chatter', root=False)
        await began(self.runtime, att)
        self.assertEqual(self.notices(), [])
        self.say('new task from greg')
        await began(self.runtime, att)
        await began(self.runtime, att)
        notices = self.notices()
        self.assertEqual(len(notices), 1)
        self.assertIn('reopen_task', notices[0]['body'])
        self.assertEqual(notices[0]['audience_attachment_id'], 'captain')
        self.assertEqual(self.row()['status'], 'approved')

    async def test_a_person_message_also_counts(self):
        await self.settle()
        self.db.add_message(self.conv_id, 'greg', 'human', 'one more thing')
        await began(self.runtime, self.db.get_attachment(self.worker.attachment_id))
        self.assertEqual(len(self.notices()), 1)

    async def test_safety_net_ignores_other_processes_and_unsettled_tasks(self):
        await self.settle()
        self.say('go on')
        await unreopened(self.runtime, {'id': 'someone', 'conv_id': self.conv_id, 'name': 'x'})
        self.assertEqual(self.notices(), [])
        await self.reopen(self.captain)
        await unreopened(self.runtime, self.db.get_attachment(self.worker.attachment_id))
        self.assertEqual(self.notices(), [])

    async def test_safety_net_retries_when_the_root_captain_is_away(self):
        await self.settle()
        self.say('go on')
        att = self.db.get_attachment(self.worker.attachment_id)
        live = self.runtime.live.pop('captain')
        await unreopened(self.runtime, att)
        self.assertEqual((self.row()['reopen_noticed'], self.notices()), (0, []))
        self.runtime.live['captain'] = live
        await unreopened(self.runtime, att)
        self.assertEqual(len(self.notices()), 1)

    async def test_packs_teach_reopen(self):
        await self.create()
        self.assertIn('reopen_task', ORCHESTRATOR)
        self.assertIn('create_task', ORCHESTRATOR)
        self.assertIn('Never just message', ORCHESTRATOR)
        self.assertIn('reopen_task', task_pack(self.db, self.conv_id, 'implementer'))
