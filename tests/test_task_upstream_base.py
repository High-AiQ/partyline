"""create_task base:"upstream": a task cut from the fetched upstream of a checkout left behind."""

import os
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import HTTPException
from pydantic import ValidationError

from partyline.mcp import tools_captain, tools_tasks
from partyline.orchestrator_contracts import TaskIn
from partyline.orchestrator_service import create_task
from tests.orchestrator_fixture import TaskFixture, git
from tests.test_task_workspaces import CLONES, WorkspaceFixture


class UpstreamFixture:
    def behind(self, repo):
        """Give ``repo`` an origin and push one more commit there; returns that commit."""
        origin = tempfile.mkdtemp(dir=self.directory.name)
        git(origin, 'init', '-q', '--bare', '-b', 'main')
        git(repo, 'remote', 'add', 'origin', origin)
        git(repo, 'push', '-q', '-u', 'origin', 'main')
        other = tempfile.mkdtemp(dir=self.directory.name)
        git(other, 'clone', '-q', origin, 'c')
        clone = os.path.join(other, 'c')
        git(clone, 'commit', '-q', '--allow-empty', '-m', 'upstream moved')
        git(clone, 'push', '-q', 'origin', 'main')
        return git(clone, 'rev-parse', 'HEAD')

    def task(self, **extra):
        return create_task(self.runtime, self.captain, 'root', TaskIn(
            name='slice', goal='Build the feature', implementer='builder', review='inspector',
            **extra))

    def line_names(self):
        return [c['name'] for c in self.db.list_conversations()]


class UpstreamTaskTest(UpstreamFixture, TaskFixture):
    async def test_upstream_task_starts_at_the_fetched_upstream_commit(self):
        moved = self.behind(self.repo)
        row = await self.task(base='upstream')
        cwd = self.db.get_conversation(row['conv_id'])['cwd']
        self.assertEqual(git(cwd, 'rev-parse', 'HEAD'), moved)

    async def test_default_base_is_still_refused_when_behind(self):
        self.behind(self.repo)
        for extra in ({}, {'base': 'head'}):
            with self.assertRaises(HTTPException) as caught:
                await self.task(**extra)
            self.assertEqual(caught.exception.status_code, 409)
            self.assertIn('base:"upstream"', caught.exception.detail)
            self.assertIn('child or task', caught.exception.detail)
        self.assertEqual(self.line_names(), ['Root'])

    async def test_head_base_is_unchanged_when_up_to_date(self):
        row = await self.task(base='head')
        cwd = self.db.get_conversation(row['conv_id'])['cwd']
        self.assertEqual(git(cwd, 'rev-parse', 'HEAD'), git(self.repo, 'rev-parse', 'main'))

    async def test_no_upstream_is_a_409_and_leaves_no_line(self):
        with self.assertRaises(HTTPException) as caught:
            await self.task(base='upstream')
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn('no upstream to cut from', caught.exception.detail)
        self.assertEqual(self.line_names(), ['Root'])

    def test_base_is_validated_and_listed_in_the_tool_schemas(self):
        with self.assertRaises(ValidationError):
            TaskIn(name='n', goal='g', implementer='i', base='tip')
        state = {'actions': ['create_task']}
        schema = tools_tasks.tool_list(state)[0]['inputSchema']
        self.assertEqual(schema['properties']['base']['enum'], ['head', 'upstream'])
        client = SimpleNamespace(home='root', request=Mock(return_value={}))
        args = {'name': 'n', 'goal': 'g', 'implementer': 'b', 'base': 'upstream'}
        tools_captain.call(client, 'captain', {'op': 'create_task', 'args': args}, state)
        client.request.assert_called_with('POST', '/api/conversations/root/tasks', args)


class UpstreamWorkspacesTest(UpstreamFixture, WorkspaceFixture):
    async def test_every_repository_is_cut_from_its_own_upstream(self):
        self.umbrella(False)
        moved = {name: self.behind(path) for name, path in self.clones.items()}
        row = await self.task(base='upstream')
        folder = self.db.get_conversation(row['conv_id'])['cwd']
        for name in CLONES:
            self.assertEqual(git(os.path.join(folder, name), 'rev-parse', 'HEAD'), moved[name])
        rows = {w['repository']: w['base_sha'] for w in
                self.db._exec('SELECT * FROM task_workspaces WHERE conv_id=?',
                              (row['conv_id'],)).fetchall()}
        self.assertEqual(rows, {self.clones[n]: moved[n] for n in CLONES})

    async def test_one_repository_without_upstream_fails_the_whole_placement(self):
        self.umbrella(False)
        self.behind(self.clones[CLONES[0]])
        with self.assertRaises(HTTPException) as caught:
            await self.task(base='upstream')
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(caught.exception.detail.count('no upstream to cut from'), 1)
        self.assertEqual(self.line_names(), ['Root'])
        self.assertFalse(os.path.exists(os.path.join(self.top, '.partyline-worktrees', 'slice')))
        for path in self.clones.values():
            self.assertEqual(git(path, 'branch', '--list', 'line/slice'), '')
