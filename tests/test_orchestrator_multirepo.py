"""A task review covering several repositories: checkouts, brief, refusals and accept."""

import os

from fastapi import HTTPException
from pydantic import ValidationError

from partyline.accept_history import accept_history
from partyline.accept_sha import register_accept_route
from partyline.orchestrator_contracts import RepositoryShaIn, ReviewRequestIn, VerdictIn
from partyline.orchestrator_service import request_review, review_verdict
from tests.orchestrator_fixture import TaskFixture, git


class MultiRepositoryReviewTest(TaskFixture):
    def make_repo(self, name):
        path = os.path.join(self.directory.name, name)
        os.makedirs(path)
        git(path, 'init', '-q', '-b', 'main')
        git(path, 'commit', '-q', '--allow-empty', '-m', 'root')
        return os.path.realpath(path)

    def commit_in(self, path, name):
        with open(os.path.join(path, name), 'w') as handle:
            handle.write(name)
        git(path, 'add', name)
        git(path, 'commit', '-q', '-m', name)
        return git(path, 'rev-parse', 'HEAD')

    async def setup_task(self):
        await self.create()
        self.line_dir = self.db.get_conversation(self.conv_id)['cwd']
        self.sibling = self.make_repo('sibling')
        self.db._exec("INSERT INTO conversation_write_grants(conv_id,path,granted_by,granted_at) "
                      "VALUES(?,?, 'greg', 0)", (self.conv_id, os.path.join(self.sibling, 'src')))
        os.makedirs(os.path.join(self.sibling, 'src'))

    async def review(self, own, other, order=('own', 'other')):
        pairs = {'own': RepositoryShaIn(repository=self.repo, sha=own),
                 'other': RepositoryShaIn(repository=self.sibling, sha=other)}
        return await request_review(
            self.runtime, self.worker, self.conv_id,
            ReviewRequestIn(repositories=[pairs[key] for key in order], what='both', where='x'))

    async def test_two_repositories_keep_their_checkouts_across_rounds(self):
        await self.setup_task()
        first = await self.review(self.commit_in(self.line_dir, 'a1'), self.commit_in(self.sibling, 'b1'))
        paths = [item['path'] for item in first['repositories']]
        self.assertEqual([item['repository'] for item in first['repositories']],
                         [self.repo, self.sibling])
        self.assertEqual(paths[0], first['review_worktree'])
        for suffix, path in zip((self.repo, self.sibling), paths, strict=True):
            self.assertEqual(path, os.path.join(suffix, '.review', f'task-{self.conv_id}'))
        ident = first['reviewer_id']
        briefs = [m['body'] for m in self.db.list_messages(self.conv_id)
                  if m['audience_attachment_id'] == ident]
        for item in first['repositories']:
            self.assertTrue(any(item['sha'] in body and item['path'] in body for body in briefs))
        self.db._exec("UPDATE attachments SET cli_session='kept' WHERE id=?", (ident,))
        await review_verdict(self.runtime, self.principal(ident), self.conv_id,
                             VerdictIn(verdict='changes', findings='more'))
        own2, other2 = self.commit_in(self.line_dir, 'a2'), self.commit_in(self.sibling, 'b2')
        second = await self.review(own2, other2, order=('other', 'own'))  # primary stays first
        self.assertEqual([item['path'] for item in second['repositories']], paths)
        self.assertEqual([git(path, 'rev-parse', 'HEAD') for path in paths], [own2, other2])
        att = self.db.get_attachment(ident)
        self.assertEqual((att['cwd'], att['cli_session']), (paths[0], 'kept'))
        self.assertEqual(git(paths[1], 'status', '--porcelain'), '')

    async def test_a_sibling_repository_can_be_primary(self):
        await self.setup_task()
        row = await request_review(
            self.runtime, self.worker, self.conv_id, ReviewRequestIn(
                repositories=[RepositoryShaIn(repository=self.sibling,
                                              sha=self.commit_in(self.sibling, 'b1'))],
                what='backend', where='x'))
        self.assertEqual(row['review_worktree'],
                         os.path.join(self.sibling, '.review', f'task-{self.conv_id}'))
        self.assertEqual(self.db.get_attachment(row['reviewer_id'])['cwd'], row['review_worktree'])

    async def test_a_repository_outside_the_subtree_is_refused(self):
        await self.setup_task()
        outsider = self.make_repo('outsider')
        with self.assertRaises(HTTPException) as refused:
            await request_review(self.runtime, self.worker, self.conv_id, ReviewRequestIn(
                repositories=[RepositoryShaIn(repository=outsider, sha=self.commit_in(outsider, 'x'))],
                what='no', where='x'))
        self.assertEqual(refused.exception.status_code, 403)
        self.assertEqual(self.row()['status'], 'implementing')
        self.assertFalse(os.path.exists(os.path.join(outsider, '.review')))

    async def test_a_repository_named_twice_or_with_a_sha_too_is_refused(self):
        await self.setup_task()
        sha = self.commit_in(self.sibling, 'b1')
        entry = {'repository': self.sibling, 'sha': sha}
        with self.assertRaises(ValidationError):
            ReviewRequestIn(sha=sha, repositories=[entry], what='w', where='x')
        with self.assertRaises(ValidationError):
            ReviewRequestIn(repositories=[entry, entry], what='w', where='x')
        self.actor = self.worker
        both = self.client.post(f'/api/conversations/{self.conv_id}/request-review', json={
            'sha': sha, 'repositories': [entry], 'what': 'w', 'where': 'x'})
        self.assertEqual(both.status_code, 422)
        aliased = os.path.join(self.directory.name, 'alias')
        os.symlink(self.sibling, aliased)
        with self.assertRaises(HTTPException) as twice:
            await request_review(self.runtime, self.worker, self.conv_id, ReviewRequestIn(
                repositories=[RepositoryShaIn(repository=self.sibling, sha=sha),
                              RepositoryShaIn(repository=aliased, sha=sha)], what='w', where='x'))
        self.assertIn(twice.exception.status_code, (403, 422))

    async def test_a_later_round_must_keep_the_primary_repository(self):
        await self.setup_task()
        await self.review(self.commit_in(self.line_dir, 'a1'), self.commit_in(self.sibling, 'b1'))
        ident = self.row()['reviewer_id']
        await review_verdict(self.runtime, self.principal(ident), self.conv_id,
                             VerdictIn(verdict='changes', findings='again'))
        with self.assertRaises(HTTPException) as moved:
            await request_review(self.runtime, self.worker, self.conv_id, ReviewRequestIn(
                repositories=[RepositoryShaIn(repository=self.sibling,
                                              sha=self.commit_in(self.sibling, 'b2'))],
                what='w', where='x'))
        self.assertEqual(moved.exception.status_code, 409)

    async def test_accept_records_every_repository(self):
        await self.setup_task()
        register_accept_route(self.app, self.runtime)
        own, other = self.commit_in(self.line_dir, 'a1'), self.commit_in(self.sibling, 'b1')
        row = await self.review(own, other)
        await review_verdict(self.runtime, self.principal(row['reviewer_id']), self.conv_id,
                             VerdictIn(verdict='approve', findings='fine'))
        self.actor = self.captain
        done = self.client.post(f'/api/conversations/{self.conv_id}/accept', json={'sha': own})
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(done.json()['repositories'], [{'repository': self.sibling, 'sha': other}])
        self.assertEqual(sorted(item['sha'] for item in accept_history(self.db, self.conv_id)),
                         sorted([own, other]))
        self.assertEqual(self.db.get_conversation(self.conv_id)['accepted_sha'], own)
        stale = self.client.post(f'/api/conversations/{self.conv_id}/accept', json={'sha': other})
        self.assertEqual(stale.status_code, 409)

    async def test_accept_without_the_line_repository_records_the_primary(self):
        await self.setup_task()
        register_accept_route(self.app, self.runtime)
        other = self.commit_in(self.sibling, 'b1')
        row = await request_review(self.runtime, self.worker, self.conv_id, ReviewRequestIn(
            repositories=[RepositoryShaIn(repository=self.sibling, sha=other)], what='w', where='x'))
        await review_verdict(self.runtime, self.principal(row['reviewer_id']), self.conv_id,
                             VerdictIn(verdict='approve', findings='fine'))
        self.actor = self.captain
        done = self.client.post(f'/api/conversations/{self.conv_id}/accept', json={'sha': other})
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(self.db.get_conversation(self.conv_id)['accepted_sha'], other)

    async def test_accept_refuses_a_reviewed_commit_that_left_its_repository(self):
        await self.setup_task()
        register_accept_route(self.app, self.runtime)
        own, other = self.commit_in(self.line_dir, 'a1'), self.commit_in(self.sibling, 'b1')
        row = await self.review(own, other)
        await review_verdict(self.runtime, self.principal(row['reviewer_id']), self.conv_id,
                             VerdictIn(verdict='approve', findings='fine'))
        stored = [{**item, 'sha': 'f' * 40} if item['repository'] == self.sibling else item
                  for item in row['repositories']]
        import json
        self.db._exec('UPDATE task_reviews SET repositories=? WHERE conv_id=?',
                      (json.dumps(stored), self.conv_id))
        self.actor = self.captain
        refused = self.client.post(f'/api/conversations/{self.conv_id}/accept', json={'sha': own})
        self.assertEqual(refused.status_code, 409)
