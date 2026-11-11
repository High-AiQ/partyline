"""Helpers hold no staffed role: an agent restarts them, but not a process it could not staff."""

from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from partyline import server
from partyline.contracts import AttachmentPatchRequest
from partyline.preset_roles import require_resume
from tests.orchestrator_fixture import TaskFixture


class HelperResumeRolesTest(TaskFixture):
    def helper(self, ident='idle', *, counts=False, preset='raw-idle-check'):
        self.db.save_preset(preset, preset, preset, 'raw', 'sh idle.sh', implements=False)
        self.db.add_attachment(ident, 'root', ident, 'raw', ['sh', 'idle.sh'], self.repo,
                               'owner', counts_toward_total=counts)
        self.db._exec('UPDATE attachments SET preset=? WHERE id=?', (preset, ident))
        self.db.set_attachment_status(ident, 'detached', 'owner')
        return ident

    def test_a_helper_resumes_without_any_role_trait(self):
        self.helper()
        self.assertIsNone(require_resume(self.db, 'idle'))

    def test_a_raw_process_in_the_worker_count_is_not_a_helper(self):
        self.helper(counts=True)
        with self.assertRaises(HTTPException) as error:
            require_resume(self.db, 'idle')
        self.assertIn('Fast implementer', error.exception.detail)

    def test_a_process_a_person_attached_needs_a_fast_implementer_preset_for_an_agent(self):
        self.db.save_preset('plain', 'plain', 'plain', 'fake', 'fake', implements=False)
        self.db.add_attachment('direct', 'root', 'direct', 'fake', ['fake'], self.repo, 'owner')
        self.db._exec("UPDATE attachments SET preset='plain' WHERE id='direct'")
        with self.assertRaises(HTTPException) as error:
            require_resume(self.db, 'direct')
        self.assertIn('Fast implementer', error.exception.detail)
        self.assertIsNone(require_resume(self.db, 'direct', person=True))
        self.db._exec("UPDATE presets SET implements=1 WHERE name='plain'")
        self.assertEqual(require_resume(self.db, 'direct'), 'implementer')

    async def test_a_task_implementer_without_the_trait_is_still_refused(self):
        row = await self.create()
        self.db._exec("UPDATE presets SET implements=0 WHERE name='builder'")
        with self.assertRaises(HTTPException) as error:
            require_resume(self.db, row['implementer_id'])
        self.assertIn('Fast implementer', error.exception.detail)

    def test_a_lead_without_the_manage_trait_is_still_refused(self):
        self.db._exec("UPDATE presets SET can_manage=0 WHERE name='inspector'")
        self.db._exec("UPDATE attachments SET preset='inspector' WHERE id='captain'")
        with self.assertRaises(HTTPException) as error:
            require_resume(self.db, 'captain')
        self.assertIn('Can manage a line', error.exception.detail)

    async def test_delete_patch_resume_of_a_raw_helper_as_an_agent(self):
        self.helper()
        server.ADAPTERS['raw'] = SimpleNamespace
        server.ADAPTER_METADATA['raw'] = {'command': ['sh']}
        await self.start(self.db.get_attachment('idle'))
        request = SimpleNamespace(state=SimpleNamespace(principal=self.captain))
        await server.detach(request, 'idle')
        self.assertNotIn(self.db.get_attachment('idle')['status'], ('running', 'starting'))
        patched = await server.edit_attachment(
            request, 'idle', AttachmentPatchRequest(command='sh new-idle.sh'))
        self.assertEqual(patched['command'], ['sh', 'new-idle.sh'])
        async def resume(ident, startup_messages=None):
            return await self.resume(ident)
        with patch.object(server, '_resume_adapter', resume):
            resumed = await server.resume_attachment(request, 'idle')
        self.assertEqual(resumed['status'], 'running')
