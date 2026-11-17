"""Nested develop checkouts, complete task batches and recoverable suite placement."""

import os
from pathlib import Path
import subprocess
from unittest.mock import patch

from fastapi import HTTPException

from partyline import task_workspaces
from partyline.orchestrator_contracts import DeliverIn, ReviewRequestIn, SuiteReopenIn, TaskIn
from partyline.orchestrator_express import deliver
from partyline.orchestrator_reopen import reopen_task
from partyline.orchestrator_service import create_task, request_review
from partyline.orchestrator_store import task
from partyline.orchestrator_suite import resolve_batch
from partyline.pack_blocks import ORCHESTRATOR
from partyline.task_workspaces import workspaces
from tests.orchestrator_fixture import TaskFixture, git


class SuitePlacementRecoveryTest(TaskFixture):
    def setUp(self):
        super().setUp()
        platform = Path(self.directory.name) / 'workspace.with-dots-and-hyphens' / 'platform'
        platform.mkdir(parents=True)
        self.repo = str(platform)
        git(platform, 'init', '-q', '-b', 'main')
        git(platform, 'commit', '-q', '--allow-empty', '-m', 'platform')
        self.repos = {}
        for name in ('backend', 'frontend'):
            path = platform / name
            path.mkdir()
            git(path, 'init', '-q', '-b', 'develop')
            git(path, 'commit', '-q', '--allow-empty', '-m', 'initial')
            self.repos[name] = str(path)
        self.db._exec("UPDATE conversations SET cwd=? WHERE id='root'", (self.repo,))
        self.body = TaskIn(name='integration', goal='Test the batch', implementer='builder', mode='suite',
            repositories=[{'repository': path, 'batch': [git(path, 'rev-parse', 'HEAD')]}
                          for path in self.repos.values()])

    async def suite(self):
        return await create_task(self.runtime, self.captain, 'root', self.body)

    def assert_placed(self, row):
        self.assertIsNone(row['creation_error'])
        cwd = self.db.get_conversation(row['conv_id'])['cwd']
        for entry in row['suite_repositories']:
            self.assertEqual(entry['path'], os.path.join(cwd, Path(entry['repository']).name))
            self.assertTrue(Path(entry['path'], '.git').is_file())
            self.assertIn(entry['path'], row['goal'])
            self.assertEqual(git(entry['repository'], 'branch', '--show-current'), 'develop')

    async def test_nested_develop_repositories_with_punctuation_get_stable_worktrees(self):
        heads = [git(path, 'rev-parse', 'HEAD') for path in self.repos.values()]
        row = await self.suite()
        self.assert_placed(row)
        self.assertEqual(len(row['repositories']), 3)
        retry = await self.suite()
        self.assertEqual(retry['suite_repositories'], row['suite_repositories'])
        for entry in row['suite_repositories']:
            git(entry['path'], 'switch', '-c', 'integration/combined', 'develop')
        done = await deliver(self.runtime, self.principal(row['implementer_id']), row['conv_id'],
                             DeliverIn(what='PASS', where='integration/combined'))
        self.assertEqual(done['status'], 'done')
        self.assertEqual([git(path, 'rev-parse', 'HEAD') for path in self.repos.values()], heads)

    async def test_partial_add_failure_returns_repository_error_without_staffing_or_fallback(self):
        original = task_workspaces.add_worktree

        def fail_backend(repo, *args, **kwargs):
            if repo == self.repos['backend']:
                return subprocess.CompletedProcess([], 1, '', 'simulated registration failure')
            return original(repo, *args, **kwargs)

        with patch('partyline.task_workspaces.add_worktree', side_effect=fail_backend):
            row = await self.suite()
        self.assertIn(self.repos['backend'], row['creation_error'])
        self.assertIn('simulated registration failure', row['creation_error'])
        self.assertEqual(workspaces(self.db, row['conv_id']), [])
        self.assertEqual(self.db.list_attachments(row['conv_id']), [])
        self.assertIsNone(self.db.get_conversation(row['conv_id'])['cwd'])
        retry = await self.suite()
        self.assertEqual(retry['conv_id'], row['conv_id'])
        self.assert_placed(retry)

    async def accepted_range(self):
        row = await self.create('none')
        tips = {}
        for name in ('backend', 'frontend'):
            space = next(item for item in workspaces(self.db, row['conv_id'])
                         if item['repository'] == self.repos[name])
            tips[name] = []
            for number in range(3 if name == 'backend' else 2):
                path = Path(space['path']) / f'change-{number}.txt'
                path.write_text(f'{name} {number}\n')
                git(space['path'], 'add', path.name)
                git(space['path'], 'commit', '-qm', f'change {number}')
                tips[name].append(git(space['path'], 'rev-parse', 'HEAD'))
        accepted = await request_review(self.runtime, self.worker, row['conv_id'],
                                       ReviewRequestIn(what='changes', where='worktrees'))
        return accepted, tips

    async def test_tags_and_ids_expand_whole_per_repository_ranges_and_shas_stay_single(self):
        accepted, tips = await self.accepted_range()
        for name, commits in tips.items():
            _, batch = resolve_batch(self.db, 'root', self.repos[name],
                                     [accepted['tag'], commits[-1], accepted['conv_id']])
            self.assertEqual([item['sha'] for item in batch], commits + [commits[-1]] + commits)
            self.assertEqual([item['task'] for item in batch],
                             [accepted['conv_id']] * len(commits) + [None] +
                             [accepted['conv_id']] * len(commits))
        self.body.repositories[0].batch = [accepted['tag']]
        self.body.repositories[1].batch = [accepted['conv_id']]
        row = await self.suite()
        for entry in row['suite_repositories']:
            git(entry['path'], 'switch', '-c', 'integration/combined', 'develop')
            for item in entry['batch']:
                git(entry['path'], 'cherry-pick', item['sha'])
            self.assertEqual(len(list(Path(entry['path']).glob('change-*.txt'))),
                             len(tips[Path(entry['repository']).name]))

    async def test_missing_or_divergent_task_base_is_actionable(self):
        accepted, _ = await self.accepted_range()
        repo = self.repos['backend']
        self.db._exec('UPDATE task_workspaces SET base_sha=? WHERE conv_id=? AND repository=?',
                      ('0' * 40, accepted['conv_id'], repo))
        with self.assertRaisesRegex(HTTPException, 'base is not an ancestor'):
            resolve_batch(self.db, 'root', repo, [accepted['tag']])
        self.db._exec('DELETE FROM task_workspaces WHERE conv_id=? AND repository=?',
                      (accepted['conv_id'], repo))
        with self.assertRaisesRegex(HTTPException, 'no recorded base'):
            resolve_batch(self.db, 'root', repo, [accepted['tag']])

    async def test_blocked_suite_replaces_batches_goal_and_repairs_legacy_platform_only_workspace(self):
        accepted, tips = await self.accepted_range()
        row = await self.suite()
        spaces = workspaces(self.db, row['conv_id'])
        for space in spaces:
            if space['repository'] != self.repo:
                git(space['repository'], 'worktree', 'remove', space['path'])
        self.db._exec('DELETE FROM task_workspaces WHERE conv_id=?', (row['conv_id'],))
        self.db._exec("UPDATE task_reviews SET status='blocked' WHERE conv_id=?", (row['conv_id'],))
        replacement = SuiteReopenIn(goal='Run corrected batch', repositories=[
            {'repository': self.repos['backend'], 'batch': [accepted['tag']]}])
        reopened = await reopen_task(self.runtime, self.captain, row['conv_id'], replacement)
        self.assertEqual(reopened['status'], 'implementing')
        self.assertEqual(len(reopened['suite_repositories']), 1)
        self.assertEqual([item['sha'] for item in reopened['suite_batch']], tips['backend'])
        self.assert_placed(reopened)
        self.assertIn('Run corrected batch', reopened['goal'])
        self.assertEqual(self.db.get_attachment(row['implementer_id'])['status'], 'running')
        entry = reopened['suite_repositories'][0]
        git(entry['path'], 'switch', '-c', 'integration/corrected', 'develop')
        for commit in entry['batch']:
            git(entry['path'], 'cherry-pick', commit['sha'])
        done = await deliver(self.runtime, self.principal(row['implementer_id']), row['conv_id'],
                             DeliverIn(what='PASS', where='integration/corrected'))
        self.assertEqual(done['status'], 'done')

    async def test_repair_failure_keeps_blocked_state_and_old_batch(self):
        row = await self.suite()
        self.db._exec("UPDATE task_reviews SET status='blocked' WHERE conv_id=?", (row['conv_id'],))
        self.db._exec('DELETE FROM task_workspaces WHERE conv_id=? AND repository=?',
                      (row['conv_id'], self.repos['backend']))
        # Existing non-Git content must never be overwritten by a repair.
        backend_path = row['suite_repositories'][0]['path']
        git(self.repos['backend'], 'worktree', 'remove', backend_path)
        Path(backend_path).mkdir()
        Path(backend_path, 'notes.txt').write_text('preserve')
        with self.assertRaisesRegex(HTTPException, 'preserve its contents'):
            await reopen_task(self.runtime, self.captain, row['conv_id'],
                              SuiteReopenIn(goal='Corrected', batch=self.body.repositories[0].batch,
                                            repository=self.repos['backend']))
        after = task(self.db, row['conv_id'])
        self.assertEqual(after['status'], 'blocked')
        self.assertEqual(after['suite_batch'], row['suite_batch'])
        self.assertEqual(Path(backend_path, 'notes.txt').read_text(), 'preserve')

    def test_captain_pack_says_suites_omit_review_and_expand_ranges(self):
        self.assertIn('Suite lines omit review', ORCHESTRATOR)
        self.assertIn('whole base_sha..accepted ranges', ORCHESTRATOR)
