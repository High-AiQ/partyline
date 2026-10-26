"""A SHA quoted in a report must be a commit in the task's worktrees, or be flagged."""

import os
import subprocess
from unittest.mock import AsyncMock, patch

from partyline.git_fence import _mirror_dir
from partyline.orchestrator_contracts import BlockedIn, ReviewRequestIn, VerdictIn
from partyline.orchestrator_notices import notify_root
from partyline.orchestrator_service import request_review, review_verdict
from partyline.orchestrator_sha_check import clip, flagged, quoted, report_text, suspected
from partyline.orchestrator_stall import blocked
from partyline.reports import MAX_BODY, get, list_for_parent
from partyline.return_path import ReturnPath
from partyline.task_workspaces import workspaces
from tests.orchestrator_fixture import TaskFixture, git

FAKE = '568b2db'


class ShaCheckTest(TaskFixture):
    def root_messages(self):
        return self.db.message_page('root', limit=100)[0]

    def flagged_notices(self):
        return [m for m in self.root_messages() if 'reported SHAs' in m['body']]

    async def escalated(self, prior, reported):
        """Stall to stage 3 with prior findings, then set the server's report text."""
        await self.create('none')
        returns = self.runtime.returns = ReturnPath(self.runtime)
        returns.grace = 0
        with patch('partyline.return_path.wait_until_quiet', AsyncMock(return_value=True)):
            await returns.turn_ended(self.worker.attachment_id)
            await returns.drain()
            reminder = next(m for m in self.db.message_page(self.conv_id, limit=100)[0]
                            if 'no hand-off' in m['body'])
            returns.note_delivered(self.worker.attachment_id, [reminder])
            await returns.turn_ended(self.worker.attachment_id)
            await returns.drain()
        self.assertEqual(self.row()['stall_stage'], 3)
        from partyline.orchestrator_notices import report
        from partyline.orchestrator_store import task
        self.db._exec("UPDATE task_reviews SET findings=? WHERE conv_id=?",
                      (reported, self.conv_id))
        await report(self.runtime, task(self.db, self.conv_id))
        self.db._exec("UPDATE task_reviews SET findings=? WHERE conv_id=?",
                      (prior, self.conv_id))

    def test_suspected_only_takes_bare_hex_tokens(self):
        self.assertEqual(suspected('commit 568b2db landed, B007 B007s deadbeef123'),
                         ['568b2db', 'deadbeef123'])
        self.assertEqual(suspected('no hash in this sentence'), [])
        self.assertEqual(suspected(''), [])

    def test_a_hash_named_as_another_kind_is_not_suspected(self):
        revision = '337337621b'
        for phrasing in (f'HF revision {revision}', f'Hugging Face model revision {revision}',
                         f'the weights at rev {revision}', f'checkpoint tag {revision}',
                         f'sha256 {revision}', f'file digest: {revision}',
                         f'the blob {revision}'):
            with self.subTest(phrasing=phrasing):
                self.assertEqual(suspected(phrasing), [])

    def test_a_qualifier_in_an_earlier_sentence_does_not_excuse_a_commit(self):
        self.assertEqual(suspected(f'the model was retrained. commit {FAKE} landed'), [FAKE])
        self.assertEqual(suspected(f'checksum noted; SHA {FAKE}'), [FAKE])

    def test_a_hash_inside_a_url_or_path_is_not_suspected(self):
        self.assertEqual(suspected(f'see https://huggingface.co/org/m/resolve/{FAKE}/config.json'),
                         [])
        self.assertEqual(suspected(f'open tests/fixtures/{FAKE}.txt'), [])

    def test_a_fabricated_commit_next_to_commit_or_sha_is_still_suspected(self):
        self.assertEqual(suspected(f'commit {FAKE}'), [FAKE])
        self.assertEqual(suspected(f'SHA {FAKE} is the fix'), [FAKE])
        self.assertEqual(suspected(f'reviewed at {FAKE}'), [FAKE])

    async def test_a_commit_that_exists_in_the_worktree_is_not_flagged(self):
        await self.create('none')
        sha = self.commit()
        self.assertEqual(quoted(self.db, self.conv_id, f'commit {sha}'), [])

    def mirror_only(self) -> str:
        """Put a commit in the line's mirror store only, not the worktree or repository."""
        elsewhere = os.path.join(self.directory.name, 'elsewhere')
        os.makedirs(elsewhere)
        git(elsewhere, 'init', '-q', '-b', 'main')
        git(elsewhere, 'commit', '-q', '--allow-empty', '-m', 'mirrored')
        landed = git(elsewhere, 'rev-parse', 'HEAD')
        patcher = patch('partyline.git_fence.FENCE_ROOT', os.path.join(self.directory.name, 'fence'))
        patcher.start()
        self.addCleanup(patcher.stop)
        repo = workspaces(self.db, self.conv_id)[0]['repository']
        mirror = _mirror_dir(os.path.join(repo, '.git'), self.conv_id)
        git(self.directory.name, 'init', '-q', '--bare', mirror)
        git(mirror, 'fetch', '-q', elsewhere, 'HEAD')
        with self.assertRaises(subprocess.CalledProcessError):
            git(repo, 'cat-file', '-e', f'{landed}^{{commit}}')
        return landed

    async def test_a_commit_only_in_the_line_mirror_store_is_not_flagged(self):
        await self.create('none')
        landed = self.mirror_only()
        self.assertEqual(quoted(self.db, self.conv_id, f'commit {landed}'), [])
        self.assertEqual(quoted(self.db, self.conv_id, f'commit {FAKE}'), [FAKE])

    async def test_a_worker_commit_held_only_by_its_mirror_is_not_flagged_in_request_review(self):
        await self.create('none')
        landed = self.mirror_only()
        row = await request_review(self.runtime, self.worker, self.conv_id,
                                   ReviewRequestIn(sha=self.commit(), what=f'landed {landed}',
                                                   where='code'))
        self.assertEqual(flagged(self.db, row), [])
        self.assertNotIn('unverified SHAs', get(self.db, row['report_id'])['body'])

    async def test_a_report_quoting_the_base_sha_of_an_unmoved_task_is_not_flagged(self):
        await self.create('none')
        base = workspaces(self.db, self.conv_id)[0]['base_sha']
        self.assertEqual(quoted(self.db, self.conv_id, f'based on {base}'), [])
        row = await blocked(self.runtime, self.worker, self.conv_id,
                            BlockedIn(reason=f'based on {base}'))
        self.assertEqual(flagged(self.db, row), [])

    def test_colour_and_short_tokens_behave_as_before(self):
        self.assertEqual(suspected('colour #ff8800, B007 and abc123'), [])
        self.assertEqual(suspected('colour #deadbee'), ['deadbee'])

    async def test_a_blocked_reason_naming_a_hf_revision_is_not_flagged(self):
        await self.create('none')
        row = await blocked(self.runtime, self.worker, self.conv_id,
                            BlockedIn(reason='HF revision 337337621b is pinned'))
        self.assertEqual(flagged(self.db, row), [])
        self.assertNotIn('unverified SHAs', get(self.db, row['report_id'])['body'])

    async def test_a_blocked_reason_claiming_a_missing_commit_is_flagged_to_the_captain(self):
        await self.create('none')
        row = await blocked(self.runtime, self.worker, self.conv_id,
                            BlockedIn(reason=f'files staged at {FAKE}'))
        self.assertEqual(row['status'], 'blocked')
        self.assertIn(FAKE, flagged(self.db, row))
        body = get(self.db, row['report_id'])['body']
        self.assertIn('unverified SHAs', body)
        self.assertIn(FAKE, body)
        self.assertEqual(self.flagged_notices()[0]['audience_attachment_id'], 'captain')

    async def test_a_live_root_captain_is_rung_once_about_a_missing_commit(self):
        await self.create('none')
        await blocked(self.runtime, self.worker, self.conv_id,
                      BlockedIn(reason=f'files staged at {FAKE}'))
        with patch('partyline.orchestrator_sha_check.post_private', new=AsyncMock()) as post:
            from partyline.orchestrator_sha_check import flag
            await flag(self.runtime, self.row(), f'files staged at {FAKE}')
        self.assertEqual(post.call_count, 1)
        self.assertIn(FAKE, post.call_args.args[4])

    async def test_request_review_hands_over_even_when_the_quoted_sha_is_missing(self):
        await self.create('none')
        row = await request_review(self.runtime, self.worker, self.conv_id,
                                   ReviewRequestIn(sha=self.commit(), what=f'landed {FAKE}',
                                                   where='code'))
        self.assertEqual(row['status'], 'done')
        self.assertIn(FAKE, flagged(self.db, row))
        self.assertIn('unverified SHAs', get(self.db, row['report_id'])['body'])

    async def test_changes_findings_quoting_a_missing_commit_are_flagged(self):
        await self.create('inspector')
        sha = self.commit()
        await request_review(self.runtime, self.worker, self.conv_id,
                             ReviewRequestIn(sha=sha, what='first', where='code'))
        row = self.row()
        await review_verdict(self.runtime, self.principal(row['reviewer_id']), self.conv_id,
                             VerdictIn(verdict='changes', findings=f'revert {FAKE}'))
        self.assertIn(FAKE, flagged(self.db, self.row()))
        self.assertEqual(len(self.flagged_notices()), 1)

    def test_clip_cuts_at_word_boundaries_and_marks_the_cut(self):
        self.assertEqual(clip('short', 10), 'short')
        self.assertEqual(clip('alpha beta gamma', 200), 'alpha beta gamma')
        self.assertEqual(clip('alpha beta gamma', 9), 'alpha …')
        self.assertEqual(clip('abcdefghij', 5), ' …')
        self.assertEqual(clip('x', 0), '')

    async def test_a_short_report_is_byte_for_byte_what_it_was(self):
        await self.create('none')
        row = await request_review(self.runtime, self.worker, self.conv_id,
                                   ReviewRequestIn(sha=self.commit(), what='landed it',
                                                   where='code'))
        expected = (f"Task {row['conv_id']}: {row['status']}; round {row['round']}; "
                    f"SHA {row['sha']}; review {row['review_worktree']}; "
                    f"{row['what']} — {row['location']}\n{row['findings']}")
        self.assertEqual(report_text(self.db, row), expected)

    async def test_long_what_and_location_give_way_so_the_findings_survive(self):
        await self.create('none')
        findings = 'word ' * 299 + 'omega'
        self.assertEqual(len(findings), 1500)
        self.db._exec(
            "UPDATE task_reviews SET what=?, location=?, findings=? WHERE conv_id=?",
            ('lorem ipsum ' * 50, 'src/dir ' * 60, findings, self.conv_id))
        body = report_text(self.db, self.row())
        self.assertLessEqual(len(body), MAX_BODY)
        self.assertTrue(body.endswith(findings))
        self.assertNotIn('lorem', body)  # `what` was given up first
        self.assertIn(' …', body)  # and the shortening is visible

    def test_findings_that_alone_exceed_the_room_are_cut_whole_word_with_a_marker(self):
        row = {'conv_id': 't', 'stall_stage': 0, 'status': 'in_review', 'round': 0,
               'sha': None, 'repositories': [], 'review_worktree': None,
               'what': 'w', 'location': 'l', 'findings': 'gamma ' * 500}
        body = report_text(self.db, row)
        self.assertLessEqual(len(body), MAX_BODY)
        self.assertTrue(body.endswith('gamma …[truncated; full text via tasks]'))

    def test_fixed_parts_that_alone_overflow_the_cap_are_clipped_with_the_marker(self):
        row = {'conv_id': 't', 'stall_stage': 0, 'status': 'in_review', 'round': 0,
               'sha': 'b' * 40, 'review_worktree': '/wt', 'what': 'w', 'location': 'l',
               'findings': 'f',
               'repositories': [{'repository': f'/repo/{i}', 'sha': 'c' * 40}
                                for i in range(40)]}
        flags = [f'{i:040x}' for i in range(30)]
        with patch('partyline.orchestrator_sha_check.flagged', return_value=flags):
            body = report_text(self.db, row)
        self.assertLessEqual(len(body), MAX_BODY)
        self.assertTrue(body.endswith(' …[truncated; full text via tasks]'))

    async def test_the_unverified_sha_warning_sits_before_whole_findings(self):
        await self.create('none')
        await request_review(self.runtime, self.worker, self.conv_id,
                             ReviewRequestIn(sha=self.commit(), what=f'landed {FAKE}',
                                             where='code'))
        self.db._exec("UPDATE task_reviews SET findings=? WHERE conv_id=?",
                      ('the work that matters', self.conv_id))
        body = report_text(self.db, self.row())
        self.assertIn(f'landed {FAKE}', body)
        self.assertLess(body.index('⚠ unverified SHAs'), body.index('the work that matters'))

    async def test_notify_root_clips_a_long_note_at_a_word_boundary(self):
        await self.create('none')
        await notify_root(self.runtime, self.row(), 'unblocked: ' + 'gamma ' * 500)
        body = list_for_parent(self.db, 'root')[0]['body']
        self.assertLessEqual(len(body), MAX_BODY)
        self.assertTrue(body.startswith(f'Task {self.conv_id}: unblocked: gamma'))
        self.assertTrue(body.endswith('gamma …'))
