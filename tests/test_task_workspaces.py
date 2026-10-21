"""A task's workspace: a worktree of every repository under the root captain's folder."""

import os

from fastapi import HTTPException

from partyline import fence_workspaces
from partyline.fence_paths import write_set
from partyline.orchestrator_contracts import ReviewRequestIn
from partyline.orchestrator_service import request_review
from partyline.task_workspaces import anchor, place_task, workspaces
from tests.orchestrator_fixture import TaskFixture, git

CLONES = ('argon-backend', 'argon-frontend')


class WorkspaceFixture(TaskFixture):
    def umbrella(self, repository):
        """The root captain's folder: holds two clones, and is itself a repository or not."""
        self.top = os.path.join(self.directory.name, 'argon-platform')
        os.makedirs(self.top)
        with open(os.path.join(self.top, 'AGENTS.md'), 'w') as fh:
            fh.write('the map')
        if repository:
            git(self.top, 'init', '-q', '-b', 'main')
            git(self.top, 'add', 'AGENTS.md')
            git(self.top, 'commit', '-q', '-m', 'platform')
        self.clones = {}
        for name in CLONES:
            path = self.clones[name] = os.path.join(self.top, name)
            os.makedirs(path)
            git(path, 'init', '-q', '-b', 'main')
            git(path, 'commit', '-q', '--allow-empty', '-m', name)
        self.db._exec("UPDATE conversations SET cwd=? WHERE id='root'", (self.top,))

    def work(self, name, message='work'):
        path = os.path.join(self.db.get_conversation(self.conv_id)['cwd'], name)
        git(path, 'commit', '-q', '--allow-empty', '-m', message)
        return git(path, 'rev-parse', 'HEAD')

    async def review(self, **body):
        return await request_review(self.runtime, self.worker, self.conv_id,
                                    ReviewRequestIn(what='w', where='x', **body))


class PlainFolderTest(WorkspaceFixture):
    async def test_a_plain_folder_gets_a_worktree_per_clone_and_the_guides(self):
        self.umbrella(False)
        with open(os.path.join(self.top, 'CLAUDE.md'), 'w') as fh:
            fh.write('claude')
        await self.create('captain')
        folder = self.db.get_conversation(self.conv_id)['cwd']
        self.assertEqual(folder, os.path.join(self.top, '.partyline-worktrees', 'slice'))
        self.assertFalse(os.path.exists(os.path.join(folder, '.git')))
        for name in CLONES:
            self.assertTrue(os.path.isfile(os.path.join(folder, name, '.git')))
            self.assertEqual(git(self.clones[name], 'rev-parse', '--verify', 'line/slice'),
                             git(self.clones[name], 'rev-parse', 'HEAD'))
        self.assertEqual([w['branch'] for w in workspaces(self.db, self.conv_id)], ['line/slice'] * 2)
        for guide in ('AGENTS.md', 'CLAUDE.md'):
            link = os.path.join(folder, guide)
            self.assertTrue(os.path.islink(link))
            self.assertEqual(os.readlink(link), os.path.join(self.top, guide))

    async def test_only_the_guides_that_exist_are_linked(self):
        self.umbrella(False)
        os.remove(os.path.join(self.top, 'AGENTS.md'))
        await self.create('captain')
        folder = self.db.get_conversation(self.conv_id)['cwd']
        self.assertEqual(sorted(os.listdir(folder)), list(CLONES))

    async def test_review_with_no_arguments_takes_each_clone_that_moved(self):
        self.umbrella(False)
        await self.create('captain')
        with self.assertRaises(HTTPException) as caught:
            await self.review()
        self.assertEqual(caught.exception.status_code, 409)
        backend = self.work('argon-backend')
        self.assertEqual((await self.review())['status'], 'in_review')
        self.assertEqual([item['sha'] for item in self.row()['repositories']], [backend])
        self.db._exec("UPDATE task_reviews SET status='implementing' WHERE conv_id=?", (self.conv_id,))
        frontend = self.work('argon-frontend')
        await self.review()
        found = {os.path.basename(i['repository']): i['sha'] for i in self.row()['repositories']}
        self.assertEqual(found, {'argon-backend': backend, 'argon-frontend': frontend})
        for item in self.row()['repositories']:
            self.assertEqual(git(item['path'], 'rev-parse', 'HEAD'), item['sha'])

    async def test_a_sha_in_any_clone_is_admitted_by_sha_alone(self):
        self.umbrella(False)
        await self.create('captain')
        sha = self.work('argon-frontend')
        await self.review(sha=sha)
        self.assertEqual(self.row()['repositories'][0]['repository'], self.clones['argon-frontend'])

    async def test_the_tips_are_anchored_in_the_real_clones(self):
        self.umbrella(False)
        await self.create('captain')
        shas = {name: self.work(name) for name in CLONES}
        anchor(self.db, self.conv_id)
        for name in CLONES:
            self.assertEqual(git(self.clones[name], 'rev-parse', 'refs/partyline/tasks/slice'), shas[name])

    async def test_two_tasks_get_separate_folders_and_branches(self):
        self.umbrella(False)
        await self.create('captain')
        first = self.conv_id
        await self.create('captain')
        self.assertNotEqual(first, self.conv_id)
        self.assertEqual(os.path.basename(self.db.get_conversation(self.conv_id)['cwd']), 'slice-2')
        self.assertEqual(git(self.clones['argon-backend'], 'rev-parse', '--verify', 'line/slice-2'),
                         git(self.clones['argon-backend'], 'rev-parse', 'HEAD'))


class RollbackTest(WorkspaceFixture):
    def test_a_clone_with_no_commit_undoes_every_worktree_made_so_far(self):
        self.umbrella(False)
        empty = os.path.join(self.top, 'argon-zzz')
        os.makedirs(empty)
        git(empty, 'init', '-q', '-b', 'main')
        self.db.create_conversation('t', 'slice')
        self.assertIsNone(place_task(self.db, 'root', 't'))
        self.assertFalse(os.path.exists(os.path.join(self.top, '.partyline-worktrees', 'slice')))
        for name in CLONES:
            self.assertEqual(git(self.clones[name], 'branch', '--list', 'line/*'), '')
            self.assertEqual(git(self.clones[name], 'worktree', 'list').count('\n'), 0)
        self.assertEqual(workspaces(self.db, 't'), [])


class RepositoryFolderTest(WorkspaceFixture):
    async def test_a_repository_folder_gets_its_own_worktree_and_one_per_clone(self):
        self.umbrella(True)
        git(self.top, 'config', 'core.excludesFile', '/dev/null')
        await self.create('captain')
        folder = self.db.get_conversation(self.conv_id)['cwd']
        self.assertTrue(os.path.isfile(os.path.join(folder, 'AGENTS.md')))
        self.assertFalse(os.path.islink(os.path.join(folder, 'AGENTS.md')))
        self.assertEqual(len(workspaces(self.db, self.conv_id)), 3)
        for name in CLONES:
            self.assertTrue(os.path.isfile(os.path.join(folder, name, '.git')))
        self.assertEqual(git(folder, 'status', '--porcelain'), '')
        self.assertEqual(git(folder, 'rev-parse', '--abbrev-ref', 'HEAD'), 'line/slice')

    async def test_a_commit_in_the_folder_and_a_clone_are_both_reviewed(self):
        self.umbrella(True)
        await self.create('captain')
        folder = self.db.get_conversation(self.conv_id)['cwd']
        git(folder, 'commit', '-q', '--allow-empty', '-m', 'platform work')
        self.work('argon-backend')
        await self.review()
        self.assertEqual(sorted(os.path.basename(i['repository']) for i in self.row()['repositories']),
                         ['argon-backend', 'argon-platform'])


class FenceTest(WorkspaceFixture):
    def attachment(self):
        att = dict(self.db.get_attachment(self.worker.attachment_id))
        att['review_worktrees'], att['scratch_worktrees'] = [], []
        fence_workspaces.load(self.db, att)
        return att

    async def test_nested_worktrees_get_git_binds_and_their_clones_are_protected(self):
        self.umbrella(False)
        await self.create('captain')
        att = self.attachment()
        self.assertEqual(sorted(os.path.basename(p) for p in fence_workspaces.checkouts(att)), list(CLONES))
        for name in CLONES:
            self.assertIn(os.path.realpath(self.clones[name]), att['protected_roots'])
        sources = [src for src, _dst, _ro in write_set(att, create=False)]
        for name in CLONES:
            self.assertTrue(any(src.endswith(f'{name}/.git/objects') for src in sources), name)

    async def test_a_forged_workspace_row_is_ignored(self):
        self.umbrella(False)
        await self.create('captain')
        att = self.attachment()
        att['task_workspaces'].append({'conv_id': 'other', 'path': self.clones['argon-backend'],
                                       'repository': self.clones['argon-backend']})
        att['task_workspaces'].append({'conv_id': att['conv_id'], 'path': self.clones['argon-backend'],
                                       'repository': self.clones['argon-backend']})
        self.assertEqual(len(fence_workspaces.checkouts(att)), 2)
