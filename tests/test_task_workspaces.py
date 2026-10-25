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

    async def test_create_task_lists_the_workspaces_before_any_review(self):
        self.umbrella(True)
        row = await self.create('captain')
        found = {item['repository']: item for item in row['repositories']}
        self.assertEqual(sorted(found), sorted([self.top] + [self.clones[name] for name in CLONES]))

    async def test_a_plain_folder_task_lists_its_clones_before_any_review(self):
        self.umbrella(False)
        row = await self.create('captain')
        self.assertEqual(sorted(item['repository'] for item in row['repositories']),
                         sorted(self.clones[name] for name in CLONES))
        self.assertTrue(all(os.path.isdir(item['path']) for item in row['repositories']))

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


class AcceptAndRetireFixture(WorkspaceFixture):
    async def finished(self, repository=False, policy='captain'):
        """A task with a commit in each clone, approved and accepted."""
        from partyline.accept_sha import register_accept_route
        from partyline.orchestrator_contracts import VerdictIn
        from partyline.orchestrator_service import review_verdict

        self.umbrella(repository)
        await self.create(policy)
        self.shas = {name: self.work(name) for name in CLONES}
        await self.review()
        await review_verdict(self.runtime, self.captain, self.conv_id,
                             VerdictIn(verdict='approve', findings='fine'))
        register_accept_route(self.app, self.runtime)
        self.actor = self.captain
        return self.client.post(f'/api/conversations/{self.conv_id}/accept',
                                json={'sha': self.row()['sha']})

    def merge_all(self):
        for name in CLONES:
            git(self.clones[name], 'merge', '-q', '--ff-only', 'line/slice')
        if os.path.isdir(os.path.join(self.top, '.git')):
            git(self.top, 'merge', '-q', '--ff-only', 'line/slice')


class AcceptTest(AcceptAndRetireFixture):
    async def test_accept_records_every_repository_and_never_moves_the_persons_branch(self):
        from partyline.accept_history import accept_history

        done = await self.finished()
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(self.row()['status'], 'done')
        self.assertEqual(sorted(item['sha'] for item in accept_history(self.db, self.conv_id)),
                         sorted(self.shas.values()))
        for name in CLONES:
            self.assertEqual(git(self.clones[name], 'rev-parse', 'line/slice'), self.shas[name])
            self.assertNotEqual(git(self.clones[name], 'rev-parse', 'main'), self.shas[name])

    async def test_accept_moves_the_task_branch_up_to_the_reviewed_commit_from_the_mirror(self):
        from unittest.mock import patch

        from partyline import git_fence

        with patch.object(git_fence, 'FENCE_ROOT', os.path.join(self.directory.name, 'fence')):
            self.umbrella(False)
            await self.create('captain')
            for name in CLONES:  # the fence keeps the tip in the mirror; the real ref stays at base
                path = os.path.join(self.db.get_conversation(self.conv_id)['cwd'], name)
                base = git(path, 'rev-parse', 'HEAD')
                gitdir = git_fence._worktree_gitdir(path)
                mirror = git_fence.refresh_mirror(git_fence.common_gitdir(gitdir), gitdir, self.conv_id)
                tip = self.work(name)
                git_fence._write_mirror_text(mirror, 'refs/heads/line/slice', tip + '\n')
                git(self.clones[name], 'update-ref', 'refs/heads/line/slice', base)
            self.assertEqual((await self.review())['status'], 'in_review')
            from partyline.task_accept import move_branches

            self.assertTrue(move_branches(self.db, self.conv_id, self.row()['repositories']))
            for item in self.row()['repositories']:
                self.assertEqual(git(item['repository'], 'rev-parse', 'line/slice'), item['sha'])


class RetirementTest(AcceptAndRetireFixture):
    async def retire(self):
        from partyline.worktree_lifecycle import archive_worktree_if_safe

        return archive_worktree_if_safe(self.db, self.conv_id)

    async def test_a_merged_plain_task_folder_is_removed_and_the_commits_stay_on_the_branches(self):
        await self.finished()
        folder = self.db.get_conversation(self.conv_id)['cwd']
        self.merge_all()
        self.assertEqual(await self.retire(), (True, None))
        self.assertFalse(os.path.exists(folder))
        for name in CLONES:
            self.assertEqual(git(self.clones[name], 'rev-parse', 'line/slice'), self.shas[name])
            self.assertEqual(git(self.clones[name], 'worktree', 'list').count('\n'), 0)

    async def test_a_merged_repository_folder_task_is_removed_with_its_nested_worktrees(self):
        await self.finished(repository=True)
        folder = self.db.get_conversation(self.conv_id)['cwd']
        self.merge_all()
        self.assertEqual(await self.retire(), (True, None))
        self.assertFalse(os.path.exists(folder))
        self.assertEqual(git(self.clones['argon-backend'], 'rev-parse', 'line/slice'),
                         self.shas['argon-backend'])

    async def test_a_dirty_worktree_keeps_the_whole_task_folder(self):
        await self.finished()
        folder = self.db.get_conversation(self.conv_id)['cwd']
        self.merge_all()
        with open(os.path.join(folder, 'argon-frontend', 'notes.txt'), 'w') as fh:
            fh.write('not committed')
        removed, reason = await self.retire()
        self.assertFalse(removed)
        self.assertIsNotNone(reason)
        self.assertTrue(os.path.exists(os.path.join(folder, 'argon-frontend', 'notes.txt')))

    async def test_unmerged_work_is_kept(self):
        await self.finished()
        removed, reason = await self.retire()
        self.assertEqual((removed, reason), (False, 'unmerged commits'))

    async def test_an_independent_clone_inside_the_folder_still_keeps_it(self):
        await self.finished()
        folder = self.db.get_conversation(self.conv_id)['cwd']
        self.merge_all()
        loose = os.path.join(folder, 'scratch-clone')
        os.makedirs(loose)
        git(loose, 'init', '-q')
        removed, reason = await self.retire()
        self.assertFalse(removed)
        self.assertIn('scratch-clone', reason)
        self.assertTrue(os.path.isdir(loose))

    async def test_teardown_copies_a_mirror_only_tip_onto_the_task_branch_first(self):
        from unittest.mock import patch

        from partyline import git_fence
        from partyline.worktree_lifecycle import remove_for_line

        with patch.object(git_fence, 'FENCE_ROOT', os.path.join(self.directory.name, 'fence')):
            self.umbrella(False)
            await self.create('captain')
            path = os.path.join(self.db.get_conversation(self.conv_id)['cwd'], 'argon-backend')
            gitdir = git_fence._worktree_gitdir(path)
            mirror = git_fence.refresh_mirror(git_fence.common_gitdir(gitdir), gitdir, self.conv_id)
            base = git(path, 'rev-parse', 'HEAD')
            tip = self.work('argon-backend')
            git_fence._write_mirror_text(mirror, 'refs/heads/line/slice', tip + '\n')
            git(self.clones['argon-backend'], 'update-ref', 'refs/heads/line/slice', base)
            remove_for_line(self.db.get_conversation(self.conv_id), self.db)
            self.assertEqual(git(self.clones['argon-backend'], 'rev-parse', 'line/slice'), tip)
            backend = self.clones['argon-backend']
            self.assertEqual(git(backend, 'rev-parse', 'refs/partyline/tasks/slice'), tip)


class ShippedTest(AcceptAndRetireFixture):
    async def test_a_plain_task_is_shipped_once_every_clone_holds_its_commits(self):
        from partyline.orchestrator_cleanup import shipped

        await self.finished()
        self.assertFalse(shipped(self.db, self.row()))
        self.merge_all()
        self.assertTrue(shipped(self.db, self.row()))
        self.work('argon-frontend', 'newer')
        self.assertFalse(shipped(self.db, self.row()))
