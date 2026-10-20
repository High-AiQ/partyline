"""Captains file memory requests for task-line workers; nobody else files across processes."""

from unittest.mock import patch

from partyline.memory_requests import register_memory_request_routes
from tests.orchestrator_fixture import TaskFixture


class TaskLineMemoryRequestTest(TaskFixture):
    async def asyncSetUp(self):
        async def resume(ident, _pending=None):
            return object()

        register_memory_request_routes(self.app, self.runtime, resume)
        host = patch("partyline.memory_requests.memory_ceiling", return_value=64 * 1024**3)
        host.start()
        self.addCleanup(host.stop)
        self.db.set_setting("default_process_memory_bytes", str(1024**3))
        await self.create()
        self.db._exec("UPDATE task_reviews SET reviewer_id='inspect' WHERE conv_id=?", (self.conv_id,))
        self.db.add_attachment("inspect", self.conv_id, "inspector", "fake", ["fake"],
                               self.repo, "owner")
        self.db._exec("UPDATE attachments SET status='running' WHERE id='inspect'")
        self.reviewer = self.db.get_attachment("inspect")

    def file(self, att_id, actor):
        self.actor = actor
        return self.client.post(f"/api/attachments/{att_id}/memory-requests",
                                json={"requested_limit": "5G", "reason": "large bundle"})

    async def test_root_captain_files_for_task_implementer_and_it_bubbles_to_root(self):
        response = self.file(self.worker.attachment_id, self.captain)
        self.assertEqual(response.status_code, 200, response.text)
        bodies = [m["body"] for m in self.db.message_page("root", limit=100)[0]]
        self.assertTrue(any("memory" in body for body in bodies))

    async def test_task_participant_cannot_file_for_the_other_participant(self):
        reviewer = self.principal(self.reviewer["id"])
        self.assertEqual(self.file(self.worker.attachment_id, reviewer).status_code, 403)
        self.assertEqual(self.file(self.reviewer["id"], self.worker).status_code, 403)

    async def test_captain_of_another_tree_is_refused(self):
        self.db.create_conversation("elsewhere", "Elsewhere")
        self.db.add_attachment("rival", "elsewhere", "rival", "fake", ["fake"], self.repo, "owner")
        self.db._exec("UPDATE attachments SET is_lead=1,status='running' WHERE id='rival'")
        rival = self.principal("rival")
        self.assertEqual(self.file(self.worker.attachment_id, rival).status_code, 403)

    async def test_process_files_for_itself(self):
        response = self.file(self.worker.attachment_id, self.worker)
        self.assertEqual(response.status_code, 200, response.text)
