"""Multi-repository task review against real sibling repositories, no mocks of git."""

import os
from unittest.mock import patch

from fastapi import HTTPException

from partyline import git_fence
from partyline.accept_history import accept_history
from partyline.accept_sha import register_accept_route
from partyline.orchestrator_contracts import RepositoryShaIn, ReviewRequestIn, VerdictIn
from partyline.orchestrator_service import request_review, review_verdict
from partyline.worktree_paths import branch_name
from partyline.write_set_routes import add_write_grant
from tests.orchestrator_fixture import TaskFixture, git


class LayoutFixture(TaskFixture):
    def layout(self, root):
        """Sibling repositories under one parent; ``root`` picks the root line's cwd."""
        self.parent = os.path.join(self.directory.name, 'argon')
        self.repos = {}
        for name in ('argon-frontend', 'argon-platform', 'argon-backend'):
            path = self.repos[name] = os.path.join(self.parent, name)
            os.makedirs(path)
            git(path, 'init', '-q', '-b', 'develop')
            git(path, 'commit', '-q', '--allow-empty', '-m', f'{name} root')
        cwd = self.parent if root == 'parent' else self.repos[root]
        self.db._exec("UPDATE conversations SET cwd=? WHERE id='root'", (cwd,))

    def commit_in(self, path, message='lint', branch='line/argon-2383-lint-vue-warnings'):
        git(path, 'checkout', '-q', '-B', branch)
        git(path, 'commit', '-q', '--allow-empty', '-m', message)
        return git(path, 'rev-parse', 'HEAD')

    async def attempt(self, **body):
        try:
            row = await request_review(self.runtime, self.worker, self.conv_id,
                                       ReviewRequestIn(what='lint', where='src', **body))
            return row['status']
        except HTTPException as exc:
            return exc.status_code, exc.detail


    async def placed(self, root, policy='captain'):
        self.layout(root)
        with patch('partyline.line_worktree.project_directory', return_value=True):
            await self.create(policy)

    def grant(self, name):
        add_write_grant(self.db, self.conv_id, self.repos[name], 'greg')

    async def refused(self, **body):
        outcome = await self.attempt(**body)
        self.assertIsInstance(outcome, tuple, outcome)
        return outcome

    def pair(self, name, sha, repository=None):
        return RepositoryShaIn(repository=repository or self.repos[name], sha=sha)


class SiblingRepositoryReviewTest(LayoutFixture):
    async def review_sibling_by_sha_and_accept(self, root):
        await self.placed(root)
        self.grant('argon-frontend')
        sha = self.commit_in(self.repos['argon-frontend'])
        self.assertEqual(await self.attempt(sha=sha), 'in_review')
        self.assertEqual([item['repository'] for item in self.row()['repositories']],
                         [self.repos['argon-frontend']])
        await review_verdict(self.runtime, self.captain, self.conv_id,
                             VerdictIn(verdict='approve', findings='fine'))
        register_accept_route(self.app, self.runtime)
        self.actor = self.captain
        done = self.client.post(f'/api/conversations/{self.conv_id}/accept', json={'sha': sha})
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(self.db.get_conversation(self.conv_id)['accepted_sha'], sha)
        self.assertEqual(self.row()['status'], 'done')
        self.assertIsNotNone(self.row()['settled_at'])

    async def test_sha_only_review_in_a_granted_sibling_under_a_plain_parent_folder(self):
        await self.review_sibling_by_sha_and_accept('parent')

    async def test_sha_only_review_in_a_granted_sibling_of_a_repository_root(self):
        await self.review_sibling_by_sha_and_accept('argon-platform')

    async def test_repository_may_be_named_by_path_inside_it_or_bare_folder_name(self):
        await self.placed('argon-platform', policy='none')
        self.grant('argon-frontend')
        sha = self.commit_in(self.repos['argon-frontend'])
        os.makedirs(os.path.join(self.repos['argon-frontend'], 'src'))
        for name in (os.path.join(self.repos['argon-frontend'], 'src'), 'argon-frontend'):
            with self.subTest(name=name):
                self.db._exec("UPDATE task_reviews SET status='implementing' WHERE conv_id=?",
                              (self.conv_id,))
                self.assertEqual(
                    await self.attempt(repositories=[self.pair('argon-frontend', sha, name)]), 'done')

    async def test_mirror_only_branch_ref_still_reviews_by_commit_and_by_tip(self):
        with patch.object(git_fence, 'FENCE_ROOT', os.path.join(self.directory.name, 'fence')):
            await self.placed('argon-frontend', policy='none')
            cwd = self.db.get_conversation(self.conv_id)['cwd']
            branch = git(cwd, 'rev-parse', '--abbrev-ref', 'HEAD')
            base = git(cwd, 'rev-parse', 'HEAD')
            gitdir = git_fence._worktree_gitdir(cwd)
            common = git_fence.common_gitdir(gitdir)
            mirror = git_fence.refresh_mirror(common, gitdir, self.conv_id)
            sha = self.commit_in_branch(cwd, 'work')
            git_fence._write_mirror_text(mirror, f'refs/heads/{branch}', sha + '\n')
            git(common, 'update-ref', f'refs/heads/{branch}', base)  # the real ref never moved
            self.assertEqual(git_fence.mirror_branch_ref(cwd, self.conv_id, branch), sha)
            self.assertEqual(git(self.repos['argon-frontend'], 'rev-parse', sha[:7] + '^{commit}'), sha)
            self.assertEqual(await self.attempt(), 'done')
            self.assertEqual(self.row()['sha'], sha)

    def commit_in_branch(self, cwd, message):
        git(cwd, 'commit', '-q', '--allow-empty', '-m', message)
        return git(cwd, 'rev-parse', 'HEAD')


class LineBranchSiblingTest(LayoutFixture):
    def line_branch(self):
        return branch_name(self.db.get_conversation(self.conv_id)['cwd'])

    async def review_and_accept(self, how):
        await self.placed('argon-platform')
        sha = self.commit_in(self.repos['argon-frontend'], branch=self.line_branch())
        body = ({'repositories': [self.pair('argon-frontend', sha)]} if how == 'repositories'
                else {'sha': sha})
        self.assertEqual(await self.attempt(**body), 'in_review')
        checkout = self.row()['repositories'][0]['path']
        self.assertTrue(os.path.isdir(checkout))
        await review_verdict(self.runtime, self.captain, self.conv_id,
                             VerdictIn(verdict='approve', findings='fine'))
        register_accept_route(self.app, self.runtime)
        self.actor = self.captain
        done = self.client.post(f'/api/conversations/{self.conv_id}/accept', json={'sha': sha})
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(self.db.get_conversation(self.conv_id)['accepted_sha'], sha)
        self.assertIn(sha, [item['sha'] for item in accept_history(self.db, self.conv_id)])
        self.assertFalse(os.path.isdir(checkout))

    async def test_ungranted_sibling_with_the_line_branch_by_repositories(self):
        await self.review_and_accept('repositories')

    async def test_ungranted_sibling_with_the_line_branch_by_sha_only(self):
        await self.review_and_accept('sha')

    async def test_a_sibling_whose_branch_does_not_match_is_refused(self):
        await self.placed('argon-platform')
        sha = self.commit_in(self.repos['argon-frontend'], branch='line/someone-else')
        self.assertEqual((await self.refused(sha=sha))[0], 400)
        self.assertEqual((await self.refused(repositories=[self.pair('argon-frontend', sha)]))[0], 403)

    async def test_the_branch_must_contain_the_commit(self):
        await self.placed('argon-platform')
        frontend = self.repos['argon-frontend']
        self.commit_in(frontend, branch=self.line_branch())
        git(frontend, 'checkout', '-q', '-B', 'stray')
        git(frontend, 'commit', '-q', '--allow-empty', '-m', 'off the line branch')
        sha = git(frontend, 'rev-parse', 'HEAD')
        self.assertEqual((await self.refused(repositories=[self.pair('argon-frontend', sha)]))[0], 403)

    async def test_a_repository_that_is_neither_sibling_nor_child_of_the_root_is_refused(self):
        await self.placed('argon-platform')
        elsewhere = os.path.join(self.directory.name, 'elsewhere', 'argon-frontend')
        os.makedirs(elsewhere)
        git(elsewhere, 'init', '-q', '-b', 'develop')
        git(elsewhere, 'commit', '-q', '--allow-empty', '-m', 'root')
        sha = self.commit_in(elsewhere, branch=self.line_branch())
        self.assertEqual((await self.refused(sha=sha))[0], 400)
        self.assertEqual(
            (await self.refused(repositories=[self.pair('x', sha, elsewhere)]))[0], 403)

    async def test_a_direct_child_of_the_root_folder_counts_as_a_candidate(self):
        await self.placed('parent', policy='none')
        # The task folder holds a worktree of the clone, on the line's branch.
        cwd = self.db.get_conversation(self.conv_id)['cwd']
        worktree = os.path.join(cwd, 'argon-backend')
        git(worktree, 'commit', '-q', '--allow-empty', '-m', 'work')
        sha = git(worktree, 'rev-parse', 'HEAD')
        self.assertEqual(await self.attempt(sha=sha), 'done')


class RefusalsNameTheAcceptedRepositoriesTest(LayoutFixture):
    async def test_ungranted_sibling_is_refused_with_what_would_work(self):
        await self.placed('argon-platform')
        sha = self.commit_in(self.repos['argon-frontend'])
        status, detail = await self.refused(sha=sha)
        self.assertEqual(status, 400)
        self.assertIn(self.repos['argon-platform'], detail)
        status, detail = await self.refused(repositories=[self.pair('argon-frontend', sha)])
        self.assertEqual(status, 403)
        self.assertIn('accepted for this line: ' + self.repos['argon-platform'], detail)
        self.assertIn('write grant', detail)

    async def test_a_repository_the_line_has_nothing_to_do_with_stays_refused(self):
        await self.placed('argon-platform')
        self.grant('argon-frontend')
        sha = self.commit_in(self.repos['argon-backend'])
        self.assertEqual((await self.refused(sha=sha))[0], 400)
        status, detail = await self.refused(repositories=[self.pair('argon-backend', sha)])
        self.assertEqual(status, 403)
        self.assertIn(self.repos['argon-frontend'], detail)

    async def test_a_commit_in_two_accepted_repositories_is_ambiguous(self):
        await self.placed('argon-platform')
        for name in ('argon-frontend', 'argon-backend'):
            self.grant(name)
        sha = self.commit_in(self.repos['argon-frontend'])
        git(self.repos['argon-backend'], 'fetch', '-q', self.repos['argon-frontend'], 'HEAD')
        status, detail = await self.refused(sha=sha)
        self.assertEqual(status, 409)
        self.assertIn('repositories=', detail)
