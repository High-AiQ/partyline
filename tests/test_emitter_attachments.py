"""Public attach and resume keep auxiliary processes outside staffed roles."""

import sqlite3

from partyline import server
from partyline.conversation_routes import register_conversation_routes
from partyline.hierarchy_routes import hierarchy_router
from partyline.line_depth import live_workers
from partyline.orchestrator_pack import task_rebrief
from partyline.preset_roles import require_resume
from partyline.role_delivery import _instructions, current_role
from tests.orchestrator_fixture import TaskFixture


class EmitterAttachmentsTest(TaskFixture):
    def setUp(self):
        super().setUp()
        server.ADAPTERS["raw"] = server.ADAPTERS["fake"]
        server.ADAPTER_METADATA["raw"] = {"command": []}
        self.db.save_preset("monitor", "Monitor", "monitor", "raw", "run")
        self.db.save_preset("events", "Events", "events", "fake", "", emitter=True)
        self.app.include_router(hierarchy_router(self.runtime))
        register_conversation_routes(self.app, self.runtime, None, None, {}, {}, self.start)
        self.app.add_api_route("/api/attachments/{att_id}/resume", server.resume_attachment,
                               methods=["POST"])

    def attach(self, conv, **payload):
        return self.client.post(f"/api/conversations/{conv}/attachments", json=payload)

    async def test_captain_can_attach_and_resume_emitters_around_live_tasks(self):
        initial = self.attach("root", name="worker", adapter="fake")
        self.assertEqual(initial.status_code, 200, initial.text)
        task = await self.create()
        self.actor = self.captain
        root = self.attach("root", name="observer", adapter="raw", preset_name="monitor")
        self.assertEqual(root.status_code, 200, root.text)
        self.assertTrue(root.json()["emitter"])
        self.assertFalse(root.json()["counts_toward_total"])
        self.assertEqual([row["id"] for row in live_workers(self.db, "root")], [initial.json()["id"]])
        conv = self.conv_id
        capabilities = self.client.get(f"/api/capabilities?conv_id={conv}").json()["actions"]
        self.assertIn("attach_emitter", capabilities)
        self.assertNotIn("attach", capabilities)
        attached = self.attach(conv, name="events", adapter="fake", preset_name="events",
                               staffing_role="emitter")
        self.assertEqual(attached.status_code, 200, attached.text)
        self.assertTrue(attached.json()["emitter"])
        self.assertTrue(attached.json()["counts_toward_total"])
        self.assertFalse(attached.json()["implements"])
        ident = attached.json()["id"]
        self.assertEqual([row["id"] for row in live_workers(self.db, conv)], [task["implementer_id"]])
        self.assertEqual(self.row()["implementer_id"], task["implementer_id"])
        self.assertIsNone(self.row()["reviewer_id"])
        with self.assertRaisesRegex(sqlite3.IntegrityError, "identity is server-owned"):
            self.db._exec("UPDATE attachments SET is_lead=1 WHERE id=?", (ident,))
        with self.assertRaisesRegex(sqlite3.IntegrityError, "exactly one implementer"):
            self.db.add_attachment("extra", conv, "extra", "fake", ["fake"], self.repo)
        self.assertEqual(task_rebrief(self.db, self.db.get_attachment(ident)), "")
        self.assertIn("auxiliary emitter", _instructions(current_role(self.db, ident), self.db))
        self.assertEqual(require_resume(self.db, ident), "emitter")
        denied = self.attach(conv, name="other", adapter="fake", preset_name="builder")
        self.assertEqual(denied.status_code, 403, denied.text)

        self.runtime.live.pop(ident)
        self.db.set_attachment_status(ident, "detached", self.db.get_attachment(ident)["runtime_owner"])
        resumed = self.client.post(f"/api/attachments/{ident}/resume")
        self.assertEqual(resumed.status_code, 200, resumed.text)
        self.assertTrue(resumed.json()["emitter"])
        next_task = await self.create()
        self.assertIsNotNone(next_task["implementer_id"])

    async def test_emitters_do_not_prevent_managed_line_splitting_and_leave_scope_intact(self):
        self.actor = self.captain
        child = self.client.post("/api/conversations/root/children", json={"name": "subline"}).json()
        conv = child["conversation"]["id"]
        captain = self.attach(conv, name="sublead", adapter="fake", preset_name="inspector",
                              staffing_role="captain")
        self.assertEqual(captain.status_code, 200, captain.text)
        attach = self.attach(conv, name="monitor", adapter="raw", command="run", counts_toward_total=True)
        self.assertEqual(attach.status_code, 200, attach.text)
        self.assertTrue(attach.json()["counts_toward_total"])
        self.actor = self.principal(captain.json()["id"])
        nested = self.client.post(f"/api/conversations/{conv}/children", json={"name": "nested"})
        self.assertEqual(nested.status_code, 201, nested.text)
        again = self.attach(conv, name="aux", adapter="fake", preset_name="events")
        self.assertEqual(again.status_code, 200, again.text)
        outside = self.attach("root", name="monitor", adapter="raw", preset_name="monitor")
        self.assertEqual(outside.status_code, 403, outside.text)
        self.actor = self.principal(attach.json()["id"])
        blocked = self.attach(conv, name="other", adapter="raw", preset_name="monitor")
        self.assertEqual(blocked.status_code, 403, blocked.text)

    async def test_emitter_attach_requires_trusted_preset_and_cannot_staff_a_role(self):
        self.actor = self.captain
        for payload in (
            {"adapter": "raw", "command": "other"},
            {"adapter": "raw", "preset_name": "monitor", "staffing_role": "implementer"},
            {"adapter": "raw", "preset_name": "monitor", "successor": True},
            {"adapter": "fake", "preset_name": "builder", "staffing_role": "emitter"},
            {"adapter": "fake", "preset_name": "builder", "emitter": True},
        ):
            response = self.attach("root", name="monitor", **payload)
            self.assertEqual(response.status_code, 403, response.text)
        altered = self.attach("root", name="monitor", adapter="raw", preset_name="monitor", command="other")
        self.assertEqual(altered.status_code, 400, altered.text)

        self.actor = self.human
        raw = self.attach("root", name="direct", adapter="raw", command="other", implements=True)
        self.assertEqual(raw.status_code, 200, raw.text)
        self.assertTrue(raw.json()["emitter"])
        self.assertFalse(raw.json()["implements"])
        appointed = self.client.post("/api/conversations/root/lead", json={"attachment_id": raw.json()["id"]})
        self.assertEqual(appointed.status_code, 403, appointed.text)
        conflict = self.attach("root", name="conflict", adapter="fake", emitter=True, reads_images=True)
        self.assertEqual(conflict.status_code, 422, conflict.text)

    async def test_emitter_attachment_keeps_existing_process_limits(self):
        self.db.set_setting("max_live_processes", "1")
        self.actor = self.captain
        for payload in ({"adapter": "raw", "preset_name": "monitor", "counts_toward_total": True},
                        {"adapter": "fake", "preset_name": "events"}):
            refused = self.attach("root", name="aux", **payload)
            self.assertEqual(refused.status_code, 409, refused.text)
        allowed = self.attach("root", name="aux", adapter="raw", preset_name="monitor")
        self.assertEqual(allowed.status_code, 200, allowed.text)
