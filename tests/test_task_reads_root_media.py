"""A task line reads media of the lines above it through every read path."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store
from partyline.auth_guard import install_auth_guard
from partyline.media import MediaStore, prepared_files
from partyline.media_routes import media_router
from partyline.orchestrator_contracts import TaskIn
from partyline.orchestrator_service import create_task, request_review
from partyline.orchestrator_contracts import ReviewRequestIn
from tests.orchestrator_fixture import TaskFixture
from tests.test_media import png

VARIANTS = ("thumb", "slim", "readable", "original")


class TaskReadsRootMediaTest(TaskFixture):
    async def asyncSetUp(self):
        self.store = MediaStore(self.db, Path(self.directory.name) / 'media')
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(media_router(self.runtime, self.store))
        self.media_client = TestClient(app)
        self.addCleanup(self.media_client.close)

    def store_on(self, line, text='frame'):
        message = self.db.add_message(line, 'greg', 'human', text)
        prepared = prepared_files([(png(), 'screen-frame', 'image/png')])
        return self.store.store(line, message['id'], prepared, 'Walkthrough frame', None)[0].id

    def headers(self, ident):
        return {'Authorization': 'Bearer ' + auth_store.ensure_api_token(self.db, ident)}

    def codes(self, headers, file_id, conv_id):
        listing = self.media_client.get(f'/api/conversations/{conv_id}/files', headers=headers)
        fetched = {self.media_client.get(f'/api/media/{file_id}/{variant}', headers=headers).status_code
                   for variant in VARIANTS}
        return listing.status_code, fetched

    async def staff_reviewer(self):
        row = await request_review(self.runtime, self.worker, self.conv_id, ReviewRequestIn(
            sha=self.commit(), what='feature', where='code'))
        return row['reviewer_id']

    async def test_task_workers_read_root_media_but_not_siblings_or_strangers(self):
        root_frame = self.store_on('root')
        await self.create()
        mine, mine_conv = self.worker.attachment_id, self.conv_id
        sibling = await create_task(self.runtime, self.captain, 'root', TaskIn(
            name='other', goal='Other work', implementer='builder', review='inspector'))
        sibling_frame = self.store_on(sibling['conv_id'])
        self.db.create_conversation('stranger', 'Stranger', 'manager_tree')
        stranger_frame = self.store_on('stranger')
        reviewer = await self.staff_reviewer()
        for who in (mine, reviewer):
            headers = self.headers(who)
            with self.subTest(who=who):
                self.assertEqual(self.codes(headers, root_frame, 'root'), (200, {200}))
                self.assertEqual(self.codes(headers, sibling_frame, sibling['conv_id']), (403, {403}))
                self.assertEqual(self.codes(headers, stranger_frame, 'stranger'), (403, {403}))
        self.assertEqual(self.media_client.get(
            f'/api/conversations/{mine_conv}/files', headers=self.headers(mine)).status_code, 200)

    async def test_get_media_is_offered_to_both_task_roles(self):
        from partyline.machine_scope import capability_state
        from partyline.mcp.tools_core import tool_list
        await self.create()
        reviewer = self.principal(await self.staff_reviewer())
        for who in (self.worker, reviewer):
            state = capability_state(self.db, who)
            names = {tool['name'] for tool in tool_list(state)}
            self.assertIn('get_media', names)
            described = next(t for t in tool_list(state) if t['name'] == 'get_media')['description']
            self.assertIn('every line above', described)

    async def test_descendants_of_a_task_read_the_whole_chain_above_them(self):
        root_frame = self.store_on('root')
        await self.create()
        task_frame = self.store_on(self.conv_id)
        self.db.create_conversation('grand', 'Grand', 'manager_tree')
        self.db._exec('UPDATE conversations SET parent_id=? WHERE id=?',
                      (self.conv_id, 'grand'))
        self.db.add_attachment('deep', 'grand', 'deep', 'fake', ['fake'], '/tmp', 'owner')
        self.db.set_attachment_status('deep', 'running', 'owner')
        headers = self.headers('deep')
        self.assertEqual(self.codes(headers, root_frame, 'root'), (200, {200}))
        self.assertEqual(self.codes(headers, task_frame, self.conv_id), (200, {200}))
        from partyline.machine_scope import allows
        self.assertFalse(allows(self.db, self.principal('deep'), 'root', 'read'))

    async def test_the_briefings_tell_captains_to_pass_media_ids(self):
        from partyline.mcp.tools_tasks import _DESCRIBE
        from partyline.pack_blocks import ORCHESTRATOR
        self.assertIn('get_media', ORCHESTRATOR)
        self.assertIn('media ids', _DESCRIBE['create_task'])
