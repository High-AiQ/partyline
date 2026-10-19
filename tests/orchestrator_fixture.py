"""Isolated repository, database and PTY substitute for task workflow tests."""

import os
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import server
from partyline.auth_guard import Principal
from partyline.db import Db
from partyline.orchestrator_contracts import TaskIn
from partyline.orchestrator_routes import orchestrator_router
from partyline.orchestrator_service import create_task
from partyline.orchestrator_store import task
from partyline.runtime import ChatRuntime


def git(cwd, *args):
    return subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=t@example.com',
                           *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class TaskFixture(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repo = os.path.join(self.directory.name, 'repo')
        os.makedirs(self.repo)
        git(self.repo, 'init', '-q', '-b', 'main')
        git(self.repo, 'commit', '-q', '--allow-empty', '-m', 'root')
        self.db = Db(os.path.join(self.directory.name, 'test.db'))
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        self.runtime.route_mentions = AsyncMock()
        self.runtime.broadcast = AsyncMock()
        self.runtime.broadcast_all = AsyncMock()
        self.db.create_conversation('root', 'Root')
        self.db._exec("UPDATE conversations SET captain_mode='orchestrator',cwd=? WHERE id='root'",
                      (self.repo,))
        self.db.add_attachment('captain', 'root', 'captain', 'fake', ['fake'], self.repo, 'owner')
        self.db._exec("UPDATE attachments SET is_lead=1,status='running' WHERE id='captain'")
        self.runtime.live['captain'] = SimpleNamespace(att={'runtime_owner': 'owner'})
        self.captain = Principal(kind='machine', name='captain', conv_id='root',
                                 attachment_id='captain', is_lead=True)
        self.human = Principal(kind='user', name='human')
        for name in ('builder', 'inspector'):
            self.db.save_preset(name, name, name, 'fake', 'fake')
        for target, value in (('runtime', self.runtime), ('ADAPTERS', {'fake': object}),
                              ('ADAPTER_METADATA', {'fake': {'command': ['fake']}}),
                              ('_start_attachment', self.start), ('_resume_adapter', self.resume)):
            patcher = patch.object(server, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app = FastAPI()
        self.app.include_router(orchestrator_router(self.runtime))
        self.actor = self.human

        @self.app.middleware('http')
        async def identity(request, call_next):
            request.state.principal = self.actor
            return await call_next(request)

        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    async def start(self, att, **kwargs):
        self.db.set_attachment_status(att['id'], 'running', att['runtime_owner'])
        async def stop():
            self.db.set_attachment_status(att['id'], 'exited', att['runtime_owner'])
        adapter = SimpleNamespace(att=att, stop=stop, proc=None)
        self.runtime.live[att['id']] = adapter
        return self.db.get_attachment(att['id'])

    async def resume(self, ident):
        att = self.db.get_attachment(ident)
        return await self.start(att)

    async def create(self, policy='inspector'):
        row = await create_task(self.runtime, self.captain, 'root', TaskIn(
            name='slice', goal='Build the feature', implementer='builder', review=policy))
        self.conv_id = row['conv_id']
        self.worker = self.principal(row['implementer_id'])
        return row

    def principal(self, ident):
        att = self.db.get_attachment(ident)
        return Principal(kind='machine', name=att['name'], attachment_id=ident,
                         conv_id=att['conv_id'], is_lead=bool(att['is_lead']))

    def row(self):
        return task(self.db, self.conv_id)

    def commit(self, message='feature'):
        cwd = self.db.get_conversation(self.conv_id)['cwd']
        git(cwd, 'commit', '--allow-empty', '-q', '-m', message)
        return git(cwd, 'rev-parse', 'HEAD')
