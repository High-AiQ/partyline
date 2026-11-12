"""Write scope is filed once for every path a task needs, or granted when the task is created."""

import os

from fastapi import HTTPException

from partyline.orchestrator_contracts import TaskIn
from partyline.orchestrator_service import create_task
from partyline.orchestrator_store import task
from partyline.worker_pack import WORKER
from partyline.orchestrator_pack import task_pack
from partyline.write_set_routes import list_write_grants
from tests.orchestrator_fixture import TaskFixture


class TaskWriteSet(TaskFixture):
    def made(self, count=3):
        paths = []
        for index in range(count):
            path = os.path.join(self.repo, f'extra{index}')
            os.makedirs(path)
            paths.append(path)
        return paths

    def body(self, **extra):
        return TaskIn(name='slice', goal='Build the feature', implementer='builder', **extra)

    async def test_write_set_at_creation_is_granted_before_the_implementer_starts(self):
        paths = self.made(6)
        row = await create_task(self.runtime, self.captain, 'root', self.body(write_set=paths))
        granted = list_write_grants(self.db, row['conv_id'])
        self.assertEqual(sorted(g['path'] for g in granted), sorted(paths))
        self.assertEqual({g['granted_by'] for g in granted}, {'captain'})
        att = self.db.get_attachment(row['implementer_id'])
        self.assertEqual(att['status'], 'running')
        self.assertFalse(self.db._exec('SELECT 1 FROM conversation_write_grant_requests').fetchall())

    async def test_creation_applies_the_authority_and_validation_of_an_approval(self):
        outside = os.path.join(self.directory.name, 'elsewhere')
        os.makedirs(outside)
        for bad, status in ((outside, 400), ('relative/path', 400), ('/var/run/docker.sock', 403)):
            with self.subTest(path=bad):
                with self.assertRaises(HTTPException) as caught:
                    await create_task(self.runtime, self.captain, 'root',
                                      self.body(write_set=[bad]))
                self.assertEqual(caught.exception.status_code, status)
        # A refusal creates nothing: no line, no task.
        self.assertEqual(self.db._exec('SELECT * FROM task_reviews').fetchall(), [])

    async def test_a_path_the_captain_cannot_grant_is_refused_whole(self):
        good, = self.made(1)
        self.db._exec("UPDATE attachments SET status='exited' WHERE id='captain'")
        with self.assertRaises(HTTPException) as caught:
            await create_task(self.runtime, self.captain, 'root', self.body(write_set=[good]))
        self.assertEqual(caught.exception.status_code, 403)
        self.assertIn(good, caught.exception.detail)
        self.assertEqual(self.db._exec('SELECT * FROM task_reviews').fetchall(), [])

    async def test_a_person_may_pre_grant_and_a_retry_is_idempotent(self):
        paths = self.made(2)
        self.actor = self.human
        first = await create_task(self.runtime, self.human, 'root', self.body(write_set=paths))
        again = await create_task(self.runtime, self.human, 'root', self.body(write_set=paths))
        self.assertEqual(first['conv_id'], again['conv_id'])
        self.assertEqual(len(list_write_grants(self.db, first['conv_id'])), 2)
        self.assertEqual(task(self.db, first['conv_id'])['status'], 'implementing')

    def test_packs_tell_the_worker_to_file_every_path_at_once(self):
        for text in (WORKER,):
            self.assertIn('every path', text)
            self.assertIn('one request', text)

    async def test_task_pack_carries_the_same_rule(self):
        row = await create_task(self.runtime, self.captain, 'root', self.body())
        pack = task_pack(self.db, row['conv_id'], 'implementer')
        self.assertIn('every path', pack)
        self.assertIn('one request', pack)
