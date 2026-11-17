"""One review checkout per task, and a dead reviewer that can be brought back."""

import asyncio
import os
from unittest.mock import patch

from fastapi import HTTPException

from partyline import reports
from partyline.auth_guard import Principal
from partyline.orchestrator_contracts import ReviewRequestIn, VerdictIn
from partyline.line_process_routes import detach_attachment
from partyline.orchestrator_revive import _pending, on_status, restart_reviewer, reviewer_exited
from partyline.review_worktrees import list_review_worktrees
from partyline.orchestrator_service import request_review, review_verdict
from tests.orchestrator_fixture import TaskFixture, git


class ReviewerRevivalTest(TaskFixture):
    async def request(self, sha=None):
        return await request_review(self.runtime, self.worker, self.conv_id,
                                    ReviewRequestIn(sha=sha, what='feature', where='code'))

    def commit_file(self, name, text='x'):
        cwd = self.db.get_conversation(self.conv_id)['cwd']
        with open(os.path.join(cwd, name), 'w') as handle:
            handle.write(text)
        git(cwd, 'add', name)
        git(cwd, 'commit', '-q', '-m', name)
        return git(cwd, 'rev-parse', 'HEAD')

    def stop_reviewer(self):
        ident = self.row()['reviewer_id']
        self.db._exec("UPDATE attachments SET status='exited' WHERE id=?", (ident,))
        self.runtime.live.pop(ident, None)
        return ident

    async def in_review(self):
        await self.create()
        return await self.request(self.commit_file('one.txt'))

    def briefs(self, ident):
        return [m for m in self.db.list_messages(self.conv_id)
                if m['audience_attachment_id'] == ident and 'Review round' in m['body']]

    async def status_event(self, ident, value):
        self.db._exec("UPDATE attachments SET status=? WHERE id=?", (value, ident))
        self.runtime.live.pop(ident, None)
        on_status(self.runtime, ident, value)
        await asyncio.gather(*list(_pending))

    def loss_notices(self, conv_id):
        return [message['body'] for message in self.db.list_messages('root')
                if message.get('audience_attachment_id') == 'captain'
                and conv_id in message['body'] and 'before delivering' in message['body']]

    async def test_round_two_keeps_the_reviewer_folder_and_session_and_drops_round_one_files(self):
        first = await self.in_review()
        path, ident = first['review_worktree'], first['reviewer_id']
        self.db._exec(
            "UPDATE attachment_context_epochs SET epoch=7 WHERE attachment_id=?", (ident,))
        self.db._exec("UPDATE attachments SET cli_session='kept' WHERE id=?", (ident,))
        with open(os.path.join(path, 'leftover.txt'), 'w') as handle:
            handle.write('round one scratch')
        with open(os.path.join(path, 'one.txt'), 'w') as handle:
            handle.write('edited by the reviewer')
        reviewer = self.principal(ident)
        await review_verdict(self.runtime, reviewer, self.conv_id,
                             VerdictIn(verdict='changes', findings='fix it'))
        sha = self.commit_file('two.txt')
        second = await self.request(sha)
        self.assertEqual(second['review_worktree'], path)
        self.assertEqual(git(path, 'rev-parse', 'HEAD'), sha)
        self.assertFalse(os.path.exists(os.path.join(path, 'leftover.txt')))
        with open(os.path.join(path, 'one.txt')) as handle:
            self.assertEqual(handle.read(), 'x')
        self.assertEqual(git(path, 'status', '--porcelain'), '')
        att = self.db.get_attachment(ident)
        self.assertEqual((att['cwd'], att['cli_session']), (path, 'kept'))
        epoch = self.db._exec(
            "SELECT epoch FROM attachment_context_epochs WHERE attachment_id=?", (ident,)
        ).fetchone()
        self.assertEqual(epoch["epoch"], 7)  # a reviewer round resumed its saved session
        self.assertEqual([row['sha'] for row in list_review_worktrees(self.db, self.conv_id)], [sha])

    async def test_asking_again_revives_a_dead_reviewer_and_resends_the_brief(self):
        row = await self.in_review()
        ident = self.stop_reviewer()
        self.assertEqual(len(self.briefs(ident)), 1)
        again = await self.request()
        self.assertEqual(again['reviewer_id'], ident)
        self.assertEqual(self.db.get_attachment(ident)['status'], 'running')
        self.assertEqual(len(self.briefs(ident)), 2)
        await self.request()  # a live reviewer is left alone
        self.assertEqual(len(self.briefs(ident)), 2)
        self.assertEqual(self.row()['round'], row['round'])

    async def test_the_manual_action_revives_and_is_limited(self):
        await self.in_review()
        ident = self.stop_reviewer()
        self.db._exec(
            "UPDATE attachment_context_epochs SET epoch=7 WHERE attachment_id=?", (ident,))
        stranger = Principal(kind='machine', name='stranger')
        with self.assertRaises(HTTPException):
            await restart_reviewer(self.runtime, stranger, self.conv_id)
        with self.assertRaises(HTTPException):
            await restart_reviewer(self.runtime, self.worker, self.conv_id)
        await restart_reviewer(self.runtime, self.captain, self.conv_id)
        self.assertEqual(self.db.get_attachment(ident)['status'], 'running')
        epoch = self.db._exec(
            "SELECT epoch FROM attachment_context_epochs WHERE attachment_id=?", (ident,)
        ).fetchone()
        self.assertEqual(epoch["epoch"], 8)  # no saved session: reviewer restart launched fresh
        with self.assertRaises(HTTPException) as live:
            await restart_reviewer(self.runtime, self.human, self.conv_id)
        self.assertEqual(live.exception.status_code, 409)
        self.stop_reviewer()
        response = self.client.post(f'/api/conversations/{self.conv_id}/task/reviewer')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.db.get_attachment(ident)['status'], 'running')

    async def test_manual_restart_needs_a_task_in_review_with_a_reviewer_preset(self):
        await self.create()
        with self.assertRaises(HTTPException) as early:
            await restart_reviewer(self.runtime, self.captain, self.conv_id)
        self.assertEqual(early.exception.status_code, 409)
        with self.assertRaises(HTTPException) as missing:
            await restart_reviewer(self.runtime, self.captain, 'nope')
        self.assertEqual(missing.exception.status_code, 404)

    async def test_an_exit_is_retried_once_and_the_second_failure_reports_and_stops(self):
        await self.in_review()
        ident = self.stop_reviewer()
        await reviewer_exited(self.runtime, ident)
        self.assertEqual(self.db.get_attachment(ident)['status'], 'running')
        self.assertEqual(self.row()['reviewer_restarts'], 1)
        self.assertEqual(reports.list_for_parent(self.db, 'root'), [])
        self.stop_reviewer()
        await reviewer_exited(self.runtime, ident)
        self.assertEqual(self.db.get_attachment(ident)['status'], 'exited')
        self.assertEqual(self.row()['reviewer_restarts'], 2)
        self.assertEqual(len(reports.list_for_parent(self.db, 'root')), 1)
        await reviewer_exited(self.runtime, ident)
        self.assertEqual(len(reports.list_for_parent(self.db, 'root')), 1)

    async def test_a_failed_retry_reports_immediately(self):
        await self.in_review()
        ident = self.stop_reviewer()
        with patch('partyline.orchestrator_revive.ensure_reviewer',
                   side_effect=HTTPException(409, 'budget full')):
            await reviewer_exited(self.runtime, ident)
        self.assertEqual(self.row()['reviewer_restarts'], 2)
        records = reports.list_for_parent(self.db, 'root')
        self.assertEqual(len(records), 1)
        self.assertIn('budget full', records[0]['body'])

    async def test_a_verdict_resets_the_retry_budget(self):
        await self.in_review()
        ident = self.stop_reviewer()
        await reviewer_exited(self.runtime, ident)
        self.assertEqual(self.row()['reviewer_restarts'], 1)
        await review_verdict(self.runtime, self.principal(ident), self.conv_id,
                             VerdictIn(verdict='changes', findings='again'))
        self.assertEqual(self.row()['reviewer_restarts'], 0)

    async def test_an_undelivered_opencode_implementer_detach_or_exit_tells_the_parent(self):
        for value in ('detached', 'exited'):
            with self.subTest(value=value):
                row = await self.create()
                ident = row['implementer_id']
                worker = self.db.get_attachment(ident)
                self.db._exec("UPDATE attachments SET adapter='opencode-v2' WHERE id=?", (ident,))
                await self.status_event(ident, value)
                notices = self.loss_notices(self.conv_id)
                self.assertEqual(len(notices), 1)
                line_name = self.db.get_conversation(self.conv_id)['name']
                self.assertIn(f"task «{line_name}» ({self.conv_id})", notices[0])
                self.assertIn(f"implementer @{worker['name']} {value}", notices[0])
                self.assertIn('restart_implementer to resume', notices[0])

    async def test_a_captain_ordered_detach_is_quiet_through_the_real_transaction(self):
        for bulk in (False, True):
            with self.subTest(bulk=bulk):
                row = await self.create()
                ident = row['implementer_id']
                adapter = self.runtime.live[ident]

                async def stop(ident=ident, adapter=adapter):
                    self.db.set_attachment_status(ident, 'detached', adapter.att['runtime_owner'])
                    on_status(self.runtime, ident, 'detached')

                adapter.stop = stop
                if bulk:
                    await self.runtime.stop_attachments(self.conv_id)
                else:
                    await detach_attachment(self.runtime, ident, survivors=False)
                await asyncio.gather(*list(_pending))
                self.assertEqual(self.loss_notices(self.conv_id), [])

    async def test_an_implementer_detach_after_delivery_is_quiet(self):
        row = await self.in_review()
        await self.status_event(row['implementer_id'], 'detached')
        self.assertEqual(self.loss_notices(self.conv_id), [])

    async def test_a_reviewer_detach_during_review_tells_the_parent(self):
        row = await self.in_review()
        ident = row['reviewer_id']
        reviewer = self.db.get_attachment(ident)
        await self.status_event(ident, 'detached')
        notices = self.loss_notices(self.conv_id)
        self.assertEqual(len(notices), 1)
        self.assertIn(f"reviewer @{reviewer['name']} detached", notices[0])
        self.assertIn('restart_reviewer to resume', notices[0])

    async def test_only_an_exit_of_an_in_review_reviewer_triggers_recovery(self):
        await self.create()
        implementer = self.row()['implementer_id']
        on_status(self.runtime, implementer, 'exited')  # stale: its row is still running
        await asyncio.gather(*list(_pending))
        await self.in_review_after_create()
        ident = self.row()['reviewer_id']
        on_status(self.runtime, ident, 'detached')  # stale: its row is still running
        await asyncio.gather(*list(_pending))
        self.assertFalse(_pending)
        self.stop_reviewer()
        on_status(self.runtime, ident, 'exited')
        await asyncio.gather(*list(_pending))
        self.assertEqual(self.db.get_attachment(ident)['status'], 'running')
        self.assertEqual(self.loss_notices(self.conv_id), [])  # the first automatic retry is quiet

    async def in_review_after_create(self):
        return await self.request(self.commit_file('one.txt'))

    async def test_an_exit_during_shutdown_changes_nothing(self):
        await self.in_review()
        ident = self.stop_reviewer()
        self.runtime.stopping = True
        on_status(self.runtime, ident, 'exited')
        self.assertFalse(_pending)
        self.assertEqual(self.db.get_attachment(ident)['status'], 'exited')
        self.assertEqual(self.row()['reviewer_restarts'], 0)
        self.assertEqual(reports.list_for_parent(self.db, 'root'), [])

