"""A task's suite picks exclude upstream history brought in by merges or rebases."""

from pathlib import Path

from partyline.orchestrator_contracts import ReviewRequestIn, TaskIn
from partyline.orchestrator_service import create_task, request_review
from partyline.orchestrator_suite import resolve_batch
from tests.orchestrator_fixture import TaskFixture, git


class SuiteBatchTest(TaskFixture):
    def change(self, cwd, filename):
        Path(cwd, filename).write_text(filename + '\n')
        git(cwd, 'add', filename)
        git(cwd, 'commit', '-qm', filename)
        return git(cwd, 'rev-parse', 'HEAD')

    async def integrated_task(self, update, *, remote_default=False):
        row = await self.create('none')
        cwd = self.db.get_conversation(row['conv_id'])['cwd']
        base = git(self.repo, 'rev-parse', 'HEAD')
        self.change(cwd, 'task-first.txt')
        self.change(self.repo, 'upstream.txt')
        git(self.repo, 'switch', '-c', 'upstream-change')
        self.change(self.repo, 'upstream-feature.txt')
        git(self.repo, 'switch', 'main')
        git(self.repo, 'merge', '--no-ff', 'upstream-change', '-m', 'Merge upstream change')
        upstream_merge = git(self.repo, 'rev-parse', 'HEAD')
        if remote_default:
            # Local main can be newer than the last fetched default branch.
            git(self.repo, 'update-ref', 'refs/remotes/origin/main', base)
            git(self.repo, 'symbolic-ref', 'refs/remotes/origin/HEAD', 'refs/remotes/origin/main')
        if update == 'merge':
            first = git(cwd, 'rev-parse', 'HEAD')
            git(cwd, 'merge', '--no-ff', 'main', '-m', 'Merge main')
        else:
            git(cwd, 'rebase', 'main')
            first = git(cwd, 'rev-parse', 'HEAD')
        second = self.change(cwd, 'task-second.txt')
        accepted = await request_review(self.runtime, self.worker, row['conv_id'],
                                       ReviewRequestIn(what='two changes', where='worktree'))
        _, batch = resolve_batch(self.db, 'root', self.repo, [accepted['tag']])
        self.assertEqual([item['sha'] for item in batch], [first, second])
        self.assertEqual([item['task'] for item in batch], [row['conv_id']] * 2)
        # An explicitly named SHA still denotes exactly that commit.
        _, explicit = resolve_batch(self.db, 'root', self.repo, [upstream_merge])
        self.assertEqual(explicit, [{'sha': upstream_merge, 'task': None}])
        suite = await create_task(self.runtime, self.captain, 'root', TaskIn(
            name='integration', goal='Check task changes', implementer='builder', mode='suite',
            repository=self.repo, batch=[row['conv_id']]))
        path = suite['suite_repositories'][0]['path']
        git(path, 'switch', '-c', 'integration/combined', 'main')
        for item in suite['suite_batch']:
            git(path, 'cherry-pick', item['sha'])
        for filename in ('task-first.txt', 'task-second.txt', 'upstream.txt', 'upstream-feature.txt'):
            self.assertEqual(Path(path, filename).read_text(), filename + '\n')
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD'), upstream_merge)
        self.assertEqual(git(self.repo, 'branch', '--show-current'), 'main')

    async def test_merge_of_main_excludes_upstream_commits_and_merge_commits(self):
        await self.integrated_task('merge')

    async def test_rebase_onto_main_excludes_upstream_commits_and_merge_commits(self):
        await self.integrated_task('rebase')

    async def test_local_main_newer_than_remote_default_is_also_excluded(self):
        await self.integrated_task('merge', remote_default=True)
