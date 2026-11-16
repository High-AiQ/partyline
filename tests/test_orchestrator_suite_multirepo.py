"""One suite coordinates accepted changes and integration tips across repositories."""

import os
from pathlib import Path
from unittest.mock import Mock, patch

from partyline.accept_history import accept_history
from partyline.accept_sha import register_accept_route
from partyline.db import Db
from partyline.mcp.tools_tasks import call, tool_list
from partyline.orchestrator_contracts import DeliverIn, ReviewRequestIn, SuiteReopenIn, TaskIn, TaskReview
from partyline.orchestrator_express import deliver
from partyline.orchestrator_goal import set_task_goal
from partyline.orchestrator_pack import task_pack
from partyline.orchestrator_reopen import reopen_task
from partyline.orchestrator_service import create_task, request_review
from partyline.orchestrator_store import task
from partyline.reports import get
from partyline.task_workspaces import workspaces
from partyline.worktree_lifecycle import archive_worktree_if_safe
from tests.orchestrator_fixture import TaskFixture, git


class MultiRepositorySuiteTest(TaskFixture):
    def setUp(self):
        clock = patch('time.time', return_value=1000.0)
        clock.start()
        self.addCleanup(clock.stop)
        dates = patch.dict(os.environ, {'GIT_AUTHOR_DATE': '2000-01-01T00:00:00Z',
                                       'GIT_COMMITTER_DATE': '2000-01-01T00:00:00Z'})
        dates.start()
        self.addCleanup(dates.stop)
        super().setUp()
        self.top = Path(self.directory.name) / 'workspace'
        self.top.mkdir()
        self.repos = {}
        for name in ('backend', 'frontend'):
            repo = self.top / name
            repo.mkdir()
            git(repo, 'init', '-q', '-b', 'main')
            git(repo, 'commit', '-q', '--allow-empty', '-m', 'initial')
            self.repos[name] = str(repo)
        self.db._exec("UPDATE conversations SET cwd=? WHERE id='root'", (str(self.top),))

    async def accepted(self, names):
        await self.create('none')
        for name in names:
            path = Path(self.db.get_conversation(self.conv_id)['cwd']) / name
            filename = f'{self.conv_id}.txt'
            (path / filename).write_text(name)
            git(path, 'add', filename)
            git(path, 'commit', '-q', '-m', filename)
        return await request_review(self.runtime, self.worker, self.conv_id,
                                    ReviewRequestIn(what='changes', where='worktrees'))

    async def suite(self):
        backend = await self.accepted(['backend'])
        frontend = await self.accepted(['frontend'])
        both = await self.accepted(['backend', 'frontend'])
        self.inputs = [
            {'repository': self.repos['backend'], 'batch': [backend['tag'], both['tag']]},
            {'repository': self.repos['frontend'], 'batch': [frontend['conv_id'], both['tag']]},
        ]
        self.sources = (backend, frontend, both)
        row = await create_task(self.runtime, self.captain, 'root', TaskIn(
            name='integration', goal='Test combined changes', implementer='builder', mode='suite',
            repositories=self.inputs))
        self.conv_id = row['conv_id']
        self.worker = self.principal(row['implementer_id'])
        return row

    def integrate(self, row):
        """Perform the runner's ordered cherry-picks in its two assigned worktrees."""
        tips = []
        for entry in row['suite_repositories']:
            git(entry['path'], 'switch', '-c', 'integration/combined', 'main')
            for commit in entry['batch']:
                git(entry['path'], 'cherry-pick', commit['sha'])
            tips.append({'repository': entry['repository'], 'sha': git(entry['path'], 'rev-parse', 'HEAD')})
        return tips

    async def test_task_tags_resolve_per_repository_and_brief_every_tree(self):
        row = await self.suite()
        self.assertEqual((row['mode'], row['policy'], row['reviewer_id']), ('suite', 'none', None))
        self.assertEqual(len(row['suite_repositories']), 2)
        self.assertEqual(len(workspaces(self.db, self.conv_id)), 2)
        for index, repo in enumerate(row['suite_repositories']):
            source = self.sources[index]
            expected = [next(item['sha'] for item in task['repositories']
                             if item['repository'] == repo['repository'])
                        for task in (source, self.sources[2])]
            self.assertEqual([item['sha'] for item in repo['batch']], expected)
            self.assertEqual([item['task'] for item in repo['batch']],
                             [source['conv_id'], self.sources[2]['conv_id']])
            self.assertIn(repo['path'], row['goal'])
            self.assertIn(repo['path'], task_pack(self.db, self.conv_id, 'implementer'))
        self.assertIn('one combined end-to-end run', task_pack(self.db, self.conv_id, 'implementer'))
        self.assertEqual(TaskReview.model_validate(row).suite_repositories[1].path,
                         row['suite_repositories'][1]['path'])
        again = Db(self.db.path)
        self.addCleanup(again.close)
        self.assertEqual(task(again, self.conv_id)['suite_repositories'], row['suite_repositories'])
        with patch('partyline.orchestrator_service.spawn') as spawn:
            retry = await create_task(self.runtime, self.captain, 'root', TaskIn(
                name='integration', goal='Test combined changes', implementer='builder', mode='suite',
                repositories=self.inputs))
        spawn.assert_not_called()
        self.assertEqual(retry['conv_id'], self.conv_id)
        for entry in self.integrate(row):
            path = next(item['path'] for item in row['suite_repositories']
                        if item['repository'] == entry['repository'])
            batch = next(item['batch'] for item in row['suite_repositories'] if item['path'] == path)
            expected_tasks = [item['task'] for item in batch]
            self.assertEqual(sorted(p.stem for p in Path(path).glob('*.txt')), sorted(expected_tasks))

    async def test_delivery_accept_reopen_and_retire_cover_both_repositories(self):
        row = await self.suite()
        tips = self.integrate(row)
        self.actor = self.worker
        response = self.client.post(f'/api/conversations/{self.conv_id}/deliver', json={
            'what': 'Both suites PASS; combined end-to-end PASS', 'where': 'integration/combined',
            'repositories': tips})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([{'repository': item['repository'], 'sha': item['sha']}
                          for item in response.json()['repositories']], tips)
        report = get(self.db, response.json()['report_id'])['body']
        for item in tips:
            self.assertIn(item['repository'], report)
            self.assertIn(item['sha'], report)
        reopened = await reopen_task(self.runtime, self.captain, self.conv_id,
                                     SuiteReopenIn(goal='Rerun the combined test'))
        self.assertEqual(reopened['suite_repositories'], row['suite_repositories'])
        for item in row['suite_repositories']:
            self.assertIn(item['path'], reopened['goal'])
        self.assertEqual(len(workspaces(self.db, self.conv_id)), 2)
        done = await deliver(self.runtime, self.worker, self.conv_id,
                             DeliverIn(what='Rerun PASS', where='integration/combined'))
        self.assertEqual(len(done['repositories']), 2)
        register_accept_route(self.app, self.runtime)
        self.actor = self.captain
        response = self.client.post(f'/api/conversations/{self.conv_id}/accept', json={'sha': done['sha']})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(sorted(item['sha'] for item in accept_history(self.db, self.conv_id)),
                         sorted(item['sha'] for item in tips))
        for item in tips:
            git(item['repository'], 'merge', '-q', '--ff-only', item['sha'])
        await self.runtime.stop_attachments(self.conv_id)
        folder = self.db.get_conversation(self.conv_id)['cwd']
        self.assertEqual(archive_worktree_if_safe(self.db, self.conv_id), (True, None))
        self.assertFalse(os.path.exists(folder))
        for item in tips:
            self.assertEqual(git(item['repository'], 'rev-parse', 'integration/combined'), item['sha'])

    async def test_delivery_requires_all_reported_tips_to_match_before_writing(self):
        row = await self.suite()
        tips = self.integrate(row)
        self.actor = self.worker
        url = f'/api/conversations/{self.conv_id}/deliver'
        for entries, status in [(tips[:1], 422), ([tips[0], tips[0]], 422),
                                ([tips[0], dict(tips[1], sha='abcd')], 400)]:
            response = self.client.post(url, json={
                'what': 'PASS', 'where': 'integration', 'repositories': entries})
            self.assertEqual(response.status_code, status, response.text)
            self.assertIsNone(self.row()['sha'])
            self.assertTrue(all(item['branch'].startswith('line/')
                                for item in workspaces(self.db, self.conv_id)))
        wrong = dict(tips[1], sha=git(self.repos['frontend'], 'rev-parse', 'main'))
        response = self.client.post(url, json={
            'what': 'PASS', 'where': 'integration', 'repositories': [tips[0], wrong]})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.row()['status'], 'implementing')

    async def test_reopen_updates_one_batch_and_preserves_other_repository(self):
        row = await self.suite()
        self.integrate(row)
        await deliver(self.runtime, self.worker, self.conv_id, DeliverIn(what='PASS', where='integration'))
        selected = row['suite_repositories'][1]
        reopened = await reopen_task(self.runtime, self.captain, self.conv_id, SuiteReopenIn(
            goal='Retest one repository', repository=selected['repository'],
            batch=[selected['batch'][0]['sha']]))
        self.assertEqual(reopened['suite_repositories'][0], row['suite_repositories'][0])
        self.assertEqual(len(reopened['suite_repositories'][1]['batch']), 1)
        goal = await set_task_goal(self.runtime, self.captain, self.conv_id, 'Run one targeted check')
        for entry in row['suite_repositories']:
            self.assertIn(entry['path'], goal['goal'])

    async def test_api_rejects_mixed_forms_duplicates_and_non_suite_repositories(self):
        self.actor = self.captain
        base = {'name': 'integration', 'goal': 'test', 'implementer': 'builder', 'mode': 'suite',
                'repositories': [{'repository': self.repos['backend'], 'batch': ['abcd']}]}
        for extra in [{'repository': self.repos['frontend']}, {'batch': []},
                      {'repositories': base['repositories'] * 2}, {'mode': 'full'}]:
            response = self.client.post('/api/conversations/root/tasks', json=base | extra)
            self.assertEqual(response.status_code, 422, response.text)
        sha = git(self.repos['backend'], 'rev-parse', 'HEAD')
        aliases = [{'repository': name, 'batch': [sha]} for name in (self.repos['backend'], 'backend')]
        response = self.client.post('/api/conversations/root/tasks', json=base | {'repositories': aliases})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn('each repository may appear once', response.text)

    async def test_reopen_accepts_replacement_batches_and_rejects_mixed_forms(self):
        row = await self.suite()
        self.integrate(row)
        await deliver(self.runtime, self.worker, self.conv_id, DeliverIn(what='PASS', where='integration'))
        self.actor = self.captain
        url = f'/api/conversations/{self.conv_id}/task/reopen'
        for extra in ({'repository': self.repos['backend']}, {'batch': ['abcd']},
                      {'repositories': self.inputs * 2}):
            response = self.client.post(url, json={
                'goal': 'Retest fixes', 'repositories': self.inputs, **extra})
            self.assertEqual(response.status_code, 422, response.text)
            self.assertEqual(self.row()['status'], 'done')
        response = self.client.post(url, json={'goal': 'Retest fixes', 'repositories': self.inputs})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['suite_repositories'], row['suite_repositories'])

    async def test_old_single_repository_rows_keep_working_after_migration(self):
        accepted = await self.accepted(['backend'])
        inputs = dict(name='legacy', goal='Retest', implementer='builder', mode='suite',
                      repository=self.repos['backend'], batch=[accepted['tag']])
        row = await create_task(self.runtime, self.captain, 'root', TaskIn(**inputs))
        self.conv_id = row['conv_id']
        self.worker = self.principal(row['implementer_id'])
        # Simulate a persisted suite from before per-repository batches existed.
        self.db._exec("UPDATE task_reviews SET suite_repositories='[]' WHERE conv_id=?", (self.conv_id,))
        self.db._exec("UPDATE conversations SET goal='Retest' WHERE id=?", (self.conv_id,))
        again = Db(self.db.path)
        self.addCleanup(again.close)
        self.assertEqual(task(again, self.conv_id)['suite_repositories'], row['suite_repositories'])
        retry = await create_task(self.runtime, self.captain, 'root', TaskIn(**inputs))
        self.assertEqual(retry['conv_id'], self.conv_id)
        self.integrate(retry)
        done = await deliver(self.runtime, self.worker, self.conv_id,
                             DeliverIn(what='PASS', where='integration'))
        self.assertEqual(len(done['repositories']), 1)
        reopened = await reopen_task(self.runtime, self.captain, self.conv_id, SuiteReopenIn(
            goal='Test another repository', repository=self.repos['frontend'],
            batch=[git(self.repos['frontend'], 'rev-parse', 'HEAD')]))
        self.assertEqual(reopened['suite_repository'], self.repos['frontend'])
        self.assertEqual(len(reopened['suite_repositories']), 1)

    async def test_blocked_requires_reason_and_reports_it_for_full_and_suite_tasks(self):
        full = await self.create()
        suite = await self.suite()
        for row in (full, suite):
            self.actor = self.principal(row['implementer_id'])
            url = f"/api/conversations/{row['conv_id']}/blocked"
            for body in ({}, {'reason': ''}, {'reason': ' \t\n'}):
                response = self.client.post(url, json=body)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertIn('reason', response.text)
            for reason in ('Need shared test credentials', 'Need both services configured'):
                response = self.client.post(url, json={'reason': reason})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertIn(reason, get(self.db, response.json()['report_id'])['body'])

    def test_mcp_schema_accepts_per_repository_batches_and_deliver_shas(self):
        inputs = {'name': 'integration', 'goal': 'test', 'implementer': 'builder', 'mode': 'suite',
                  'repositories': [{'repository': path, 'batch': ['abcd']} for path in self.repos.values()]}
        client = Mock(home='root')
        call(client, 'create_task', inputs, {'actions': ['create_task']})
        client.request.assert_called_once_with('POST', '/api/conversations/root/tasks', inputs)
        tool = tool_list({'actions': ['create_task']})[0]
        self.assertIn('repositories', tool['inputSchema']['properties'])
        self.assertIn('combined end-to-end', tool['description'])
        body = {'what': 'PASS', 'where': 'integration',
                'repositories': [{'repository': path, 'sha': 'abcd'} for path in self.repos.values()]}
        call(client, 'deliver', body, {'actions': ['deliver']})
        client.request.assert_called_with('POST', '/api/conversations/root/deliver', body)
