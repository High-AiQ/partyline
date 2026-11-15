"""Ordered suite batches, reviewer-free delivery, reopen and legacy mode compatibility."""

import json
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from partyline.conversation_contracts import ConversationResponse
from partyline.db import Db
from partyline.machine_scope import allows
from partyline.orchestrator_contracts import (
    DeliverIn, ReviewRequestIn, SuiteReopenIn, TaskIn, TaskReview)
from partyline.orchestrator_express import deliver
from partyline.orchestrator_pack import task_pack
from partyline.orchestrator_reopen import reopen_task
from partyline.orchestrator_service import create_task, request_review
from partyline.orchestrator_stall import reminder
from partyline.orchestrator_suite import resolve_batch
from partyline.reports import list_for_parent
from tests.orchestrator_fixture import TaskFixture, git


class SuiteTest(TaskFixture):
    async def accepted(self):
        row = await self.create('none')
        sha = self.commit()
        row = await request_review(self.runtime, self.worker, self.conv_id,
                                   ReviewRequestIn(sha=sha, what='feature', where='code'))
        return row, sha

    async def suite(self, batch, **extra):
        row = await create_task(self.runtime, self.captain, 'root', TaskIn(
            name='batch', goal='Test the merged batch', implementer='builder', mode='suite',
            repository=self.repo, batch=batch, **extra))
        self.conv_id = row['conv_id']
        self.worker = self.principal(row['implementer_id'])
        return row

    async def test_ordered_task_ids_tags_and_explicit_shas_are_resolved_and_persisted(self):
        accepted, sha = await self.accepted()
        row = await self.suite([accepted['conv_id'], sha, accepted['tag']])
        self.assertEqual((row['mode'], row['policy'], row['reviewer_id']), ('suite', 'none', None))
        self.assertEqual([item['sha'] for item in row['suite_batch']], [sha] * 3)
        self.assertEqual([item['task'] for item in row['suite_batch']],
                         [accepted['conv_id'], None, accepted['conv_id']])
        again = Db(self.db.path)
        self.addCleanup(again.close)
        self.assertEqual(json.loads(again._exec('SELECT suite_batch FROM task_reviews WHERE conv_id=?',
                                               (self.conv_id,)).fetchone()[0]), row['suite_batch'])
        self.assertEqual(TaskReview.model_validate(row).suite_repository, self.repo)
        self.assertTrue(allows(self.db, self.worker, self.conv_id, 'deliver'))
        self.assertFalse(allows(self.db, self.worker, self.conv_id, 'request_review'))
        pack = task_pack(self.db, self.conv_id, 'implementer')
        for phrase in ['no reviewer', sha, 'current main', 'cherry-pick', 'best-effort',
                       'Do not push or open the PR', 'coverage', 'tests/ui/', 'deliver(what, where)']:
            self.assertIn(phrase, pack)
        self.assertNotIn('request_review', pack)
        self.assertNotIn('reviewer of this task', pack)
        self.assertIn('deliver', reminder(self.db, self.db.get_attachment(row['implementer_id'])))

    async def test_unaccepted_foreign_unknown_and_wrong_repository_batches_are_refused(self):
        row = await self.create()
        for repository, batch in [(self.repo, [row['tag']]), (self.repo, ['missing-task']),
                                  ('unknown-repo', ['abcdef1']), (self.repo, ['abcdef1'])]:
            with self.subTest(repository=repository, batch=batch), self.assertRaises(HTTPException):
                resolve_batch(self.db, 'root', repository, batch)
        accepted, sha = await self.accepted()
        self.db._exec("UPDATE task_reviews SET root_id='elsewhere' WHERE conv_id=?", (accepted['conv_id'],))
        with self.assertRaises(HTTPException):
            resolve_batch(self.db, 'root', self.repo, [accepted['tag']])
        self.db._exec("UPDATE task_reviews SET root_id='root',repositories='[]' WHERE conv_id=?",
                      (accepted['conv_id'],))
        with self.assertRaises(HTTPException):
            resolve_batch(self.db, 'root', self.repo, [accepted['conv_id']])

    async def test_suite_requires_inputs_and_refuses_review(self):
        for inputs in [{}, {'repository': self.repo}, {'batch': ['abcdef1']}]:
            with self.assertRaises(ValidationError):
                TaskIn(name='suite', goal='test', implementer='builder', mode='suite', **inputs)
        _, sha = await self.accepted()
        with self.assertRaises(HTTPException):
            await self.suite([sha], review='inspector')
        await self.suite([sha])
        with self.assertRaises(HTTPException) as caught:
            await request_review(self.runtime, self.worker, self.conv_id,
                                 ReviewRequestIn(sha=sha, what='tests', where='branch'))
        self.assertEqual(caught.exception.status_code, 409)

    async def test_delivery_records_integration_branch_tip_and_reopen_replaces_batch(self):
        accepted, sha = await self.accepted()
        await self.suite([accepted['tag']])
        cwd = self.db.get_conversation(self.conv_id)['cwd']
        git(cwd, 'switch', '-c', 'integration/batch', 'main')
        integration = self.commit('integration')
        body = DeliverIn(what='unit PASS; browser FAIL; best-effort attribution: feature task',
                         where=f'integration/batch {integration}')
        done = await deliver(self.runtime, self.worker, self.conv_id, body)
        self.assertEqual((done['status'], done['sha']), ('done', integration))
        self.assertEqual(done['repositories'][0]['sha'], integration)
        reports = list_for_parent(self.db, 'root')
        self.assertIn('suite done', reports[-1]['body'])
        await deliver(self.runtime, self.worker, self.conv_id, body)
        self.assertEqual(len(list_for_parent(self.db, 'root')), len(reports))
        self.actor = self.captain
        reopened = self.client.post(f'/api/conversations/{self.conv_id}/task/reopen',
                                    json={'goal': 'Retest fixes', 'batch': [sha, integration]})
        self.assertEqual(reopened.status_code, 200, reopened.text)
        self.assertEqual([item['sha'] for item in reopened.json()['suite_batch']], [sha, integration])
        self.assertEqual(reopened.json()['mode'], 'suite')
        self.assertIsNone(reopened.json()['reviewer_id'])

    async def test_full_reopen_refuses_suite_inputs_and_legacy_rows_normalize(self):
        row, sha = await self.accepted()
        with self.assertRaises(HTTPException):
            await reopen_task(self.runtime, self.captain, self.conv_id,
                              SuiteReopenIn(goal='again', batch=[sha]))
        self.db._exec("UPDATE task_reviews SET mode='light' WHERE conv_id=?", (self.conv_id,))
        self.assertEqual(self.row()['mode'], 'full')
        self.assertEqual(ConversationResponse.model_validate(self.db.get_conversation(self.conv_id)).task_mode,
                         'full')
        again = Db(self.db.path)
        self.addCleanup(again.close)
        self.assertEqual(again.get_conversation(self.conv_id)['task_mode'], 'full')
        for role in ['implementer', 'reviewer']:
            pack = task_pack(self.db, self.conv_id, role)
            self.assertIn('never the full suite, never e2e suites, never whole-suite coverage', pack)
            self.assertIn('List every test command', pack)

    async def test_creation_retry_keeps_the_resolved_batch(self):
        _, sha = await self.accepted()
        first = await self.suite([sha])
        with patch('partyline.orchestrator_service.spawn') as spawn:
            again = await self.suite([sha])
        spawn.assert_not_called()
        self.assertEqual(first['conv_id'], again['conv_id'])
        with self.assertRaises(HTTPException) as caught:
            await self.suite([sha, sha])
        self.assertEqual(caught.exception.status_code, 409)

    async def test_task_mode_is_bound_for_every_task_process_before_spawning(self):
        from partyline.adapters.briefing import child_env
        from partyline.role_delivery import bind_role_delivery
        row = await self.create()
        att = self.db.get_attachment(row['implementer_id'])
        att['digest_rider'] = lambda: ''
        bind_role_delivery(self.db, att, self.runtime)
        self.assertEqual(child_env({}, att)['PARTYLINE_TASK_MODE'], 'full')
        self.db._exec("UPDATE task_reviews SET mode='suite' WHERE conv_id=?", (self.conv_id,))
        # _instructions reads the suite pack, which needs the resolved batch inputs.
        self.db._exec("UPDATE task_reviews SET suite_repository=? WHERE conv_id=?", (self.repo, self.conv_id))
        bind_role_delivery(self.db, att, self.runtime)
        self.assertEqual(child_env({}, att)['PARTYLINE_TASK_MODE'], 'suite')

    async def test_delivery_reads_a_private_integration_ref_and_anchors_its_commit(self):
        import os
        from partyline.git_fence import _worktree_gitdir, common_gitdir, refresh_mirror
        from partyline.task_workspaces import workspaces
        _, sha = await self.accepted()
        row = await self.suite([sha])
        space = workspaces(self.db, self.conv_id)[0]
        git(space['path'], 'switch', '-c', 'integration/private', 'main')
        integration = self.commit('merged batch')
        gitdir = _worktree_gitdir(space['path'])
        with patch('partyline.git_fence.FENCE_ROOT', os.path.join(self.directory.name, 'mirrors')):
            refresh_mirror(common_gitdir(gitdir), gitdir, self.conv_id, protected=space['branch'])
            git(self.repo, 'update-ref', '-d', 'refs/heads/integration/private')
            done = await deliver(self.runtime, self.worker, self.conv_id,
                                 DeliverIn(what='unit PASS', where='integration/private'))
        self.assertEqual(done['sha'], integration)
        self.assertEqual(workspaces(self.db, self.conv_id)[0]['branch'], 'integration/private')
        self.assertEqual(git(self.repo, 'rev-parse', 'refs/partyline/tasks/integration/private'), integration)
        self.assertIsNone(row['reviewer_id'])

    async def test_missing_suite_workspace_returns_conflict_without_finishing_delivery(self):
        _, sha = await self.accepted()
        await self.suite([sha])
        self.db._exec('DELETE FROM task_workspaces WHERE conv_id=?', (self.conv_id,))
        self.actor = self.worker
        response = self.client.post(f'/api/conversations/{self.conv_id}/deliver',
                                    json={'what': 'unit PASS', 'where': 'integration/batch'})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn('no workspace', response.json()['detail'])
        self.assertEqual(self.row()['status'], 'implementing')
