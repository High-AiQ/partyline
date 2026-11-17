"""Suite discovery, persisted identities and delivery across root folder layouts."""

import json
import os
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from partyline.db import Db
from partyline.orchestrator_contracts import DeliverIn, TaskIn
from partyline.orchestrator_express import deliver
from partyline.orchestrator_service import create_task
from partyline.orchestrator_store import task
from partyline.orchestrator_suite import record_integration
from partyline.task_workspaces import workspaces
from tests.orchestrator_fixture import TaskFixture, git


class SuiteWorkspaceIdentityTest(TaskFixture):
    def clone(self, path):
        path.mkdir(parents=True)
        git(path, 'init', '-q', '-b', 'main')
        git(path, 'commit', '-q', '--allow-empty', '-m', 'initial')
        return str(path)

    async def run_layout(self, cwd, repositories):
        self.db._exec("UPDATE conversations SET cwd=? WHERE id='root'", (cwd,))
        row = await create_task(self.runtime, self.captain, 'root', TaskIn(
            name='integration', goal='Run checks', implementer='builder', mode='suite',
            repositories=[{'repository': repo, 'batch': [git(repo, 'rev-parse', 'HEAD')]}
                          for repo in repositories]))
        for entry in workspaces(self.db, row['conv_id']):
            git(entry['path'], 'switch', '-c', 'integration/combined')
        done = await deliver(self.runtime, self.principal(row['implementer_id']), row['conv_id'],
                             DeliverIn(what='PASS', where='integration/combined'))
        self.assertEqual(done['status'], 'done')
        self.assertTrue(all(entry['path'] for entry in done['suite_repositories']))
        self.assertEqual(len(done['repositories']), len(repositories))
        self.assertTrue(all(space['branch'] == 'integration/combined'
                            for space in workspaces(self.db, row['conv_id'])
                            if space['repository'] in repositories))
        return row

    async def test_repository_root(self):
        await self.run_layout(self.repo, [self.repo])

    async def test_trailing_slash_with_nested_repository(self):
        backend = self.clone(Path(self.repo) / 'backend')
        await self.run_layout(self.repo + '/', [self.repo, backend])

    async def test_symlinked_code_folder_with_nested_repository(self):
        backend = self.clone(Path(self.repo) / 'backend')
        alias = Path(self.directory.name) / 'code-link'
        alias.symlink_to(self.repo, target_is_directory=True)
        await self.run_layout(str(alias), [self.repo, backend])

    async def test_subdirectory_of_repository(self):
        inside = Path(self.repo) / 'src'
        inside.mkdir()
        backend = self.clone(Path(self.repo) / 'backend')
        await self.run_layout(str(inside), [self.repo, backend])

    async def test_plain_folder_of_repositories(self):
        folder = Path(self.directory.name) / 'workspace'
        repos = [self.clone(folder / name) for name in ('backend', 'frontend')]
        await self.run_layout(str(folder), repos)

    async def test_symlinked_plain_folder_of_repositories(self):
        folder = Path(self.directory.name) / 'workspace'
        repos = [self.clone(folder / name) for name in ('backend', 'frontend')]
        alias = Path(self.directory.name) / 'workspace-link'
        alias.symlink_to(folder, target_is_directory=True)
        await self.run_layout(str(alias) + '/', repos)

    async def test_root_is_a_linked_worktree_with_nested_repository_in_main(self):
        backend = self.clone(Path(self.repo) / 'backend')
        linked = str(Path(self.directory.name) / 'linked')
        git(self.repo, 'worktree', 'add', '-b', 'feature', linked)
        await self.run_layout(linked, [self.repo, backend])

    async def test_case_insensitive_volume_uses_filesystem_identity(self):
        backend = self.clone(Path(self.repo) / 'backend')
        row = await self.run_layout(self.repo, [backend])
        legacy = backend.upper()
        row['suite_repositories'][0]['repository'] = legacy
        self.db._exec('UPDATE task_workspaces SET branch=? WHERE conv_id=? AND repository=?',
                      ('line/integration', row['conv_id'], backend))
        samefile = os.path.samefile
        with patch('os.path.samefile', side_effect=lambda left, right: (
                True if {left, right} == {backend, legacy} else samefile(left, right))):
            record_integration(self.db, row)
        self.assertEqual(next(space['branch'] for space in workspaces(self.db, row['conv_id'])
                              if space['repository'] == backend), 'integration/combined')

    async def test_existing_suite_and_workspace_aliases_survive_reopen_of_database(self):
        row = await self.run_layout(self.repo, [self.repo])
        alias = Path(self.directory.name) / 'legacy-link'
        alias.symlink_to(self.repo, target_is_directory=True)
        selected = [{**row['suite_repositories'][0], 'repository': str(alias) + '/'}]
        self.db._exec('UPDATE task_reviews SET suite_repositories=? WHERE conv_id=?',
                      (json.dumps(selected), row['conv_id']))
        reopened = Db(self.db.path)
        self.addCleanup(reopened.close)
        legacy = task(reopened, row['conv_id'])
        self.assertEqual(legacy['suite_repositories'][0]['path'],
                         row['suite_repositories'][0]['path'])
        record_integration(reopened, legacy)
        self.db._exec('UPDATE task_workspaces SET repository=? WHERE conv_id=?',
                      (str(alias), row['conv_id']))
        record_integration(self.db, row)
        self.assertEqual(workspaces(self.db, row['conv_id'])[0]['branch'], 'integration/combined')

    async def test_missing_workspace_names_expected_available_and_next_step(self):
        backend = self.clone(Path(self.repo) / 'backend')
        row = await self.run_layout(self.repo, [backend])
        self.db._exec('DELETE FROM task_workspaces WHERE conv_id=? AND repository=?',
                      (row['conv_id'], backend))
        with self.assertRaises(HTTPException) as caught:
            record_integration(self.db, row)
        self.assertEqual(caught.exception.status_code, 409)
        for text in (backend, self.repo, 'workspace', 'captain', 'recreate'):
            self.assertIn(text, caught.exception.detail)
