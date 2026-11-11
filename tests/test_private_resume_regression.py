"""Private task mail must not be mistaken for an answered question."""

from unittest.mock import AsyncMock, patch

from partyline.orchestrator_contracts import MessageTaskIn
from partyline.orchestrator_handles import message_task
from partyline.reattach import ResumedAttachment
from partyline.resume_continuation import drain
from partyline.write_set_requests import resume_line_attachments
from tests.orchestrator_fixture import TaskFixture


class PrivateResumeRegression(TaskFixture):
    async def test_write_set_resume_keeps_unproved_private_mail(self):
        await self.create()
        self.runtime.route_mentions = type(self.runtime).route_mentions.__get__(self.runtime)
        ident = self.worker.attachment_id
        old = self.runtime.live[ident]
        old.att['adapter_metadata'] = {'delivery_proof': 'transcript-user-record'}
        old.deliver = AsyncMock(return_value=False)
        await message_task(self.runtime, self.captain, self.conv_id,
                           MessageTaskIn(text='Take option 1', to='implementer'))
        self.assertTrue(any('Take option 1' in m['body']
                            for m in old.deliver.await_args.args[0]))
        self.db.add_message(self.conv_id, self.worker.name, 'agent', 'Which option, @captain?')
        observed = []

        async def detach(runtime, att_id, **kwargs):
            runtime.live.pop(att_id)
            self.db.set_attachment_status(att_id, 'exited', old.att['runtime_owner'])

        async def resume(att_id, pending):
            observed.extend(pending)
            adapter = type('Adapter', (), {'att': old.att,
                'wait_startup_delivery_received': AsyncMock(return_value=True)})()
            return ResumedAttachment(adapter, True)

        with patch('partyline.write_set_requests.detach_attachment', detach):
            await resume_line_attachments(self.runtime, self.conv_id, resume)
            await drain()
        self.assertEqual(sum('Take option 1' in m['body'] for m in observed), 1)
