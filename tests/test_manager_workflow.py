"""End-to-end manager workflow against the hierarchy HTTP contract."""

import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens, server
from partyline.auth_guard import install_auth_guard
from partyline.compact_routes import register_compact_route
from partyline.conversation_routes import register_conversation_routes
from partyline.db import Db
from partyline.hierarchy_routes import hierarchy_router
from partyline.media import MediaStore
from partyline.media_routes import media_router
from partyline.preset_routes import presets_router
from partyline.runtime import ChatRuntime


class ManagerWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.runtime = ChatRuntime(self.db)
        self.media = MediaStore(self.db, self.directory.name + "/media")
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(hierarchy_router(self.runtime))
        app.include_router(media_router(self.runtime, self.media))
        app.include_router(presets_router(self.runtime, {}))
        register_compact_route(app, self.runtime, object())

        @app.post("/api/adapters/reload")
        def reload_adapter_definitions():
            return {"loaded": []}

        async def fake_start(att, **kwargs):
            return {"id": att["id"], "name": att["name"], "status": att["status"]}

        register_conversation_routes(
            app, self.runtime, self.media, None, {}, {}, fake_start
        )
        self.client = TestClient(app)
        self.db.create_conversation("root", "Root")
        self.db.add_attachment("root-mgr", "root", "astra", "fake", ["fake"], "/tmp")
        self.db.add_attachment("root-impl", "root", "grok", "fake", ["fake"], "/tmp")
        # Not live: a line carrying a live worker is assigned, not split.
        self.db.set_attachment_status("root-impl", "detached", None)
        user = auth_store.create_user(
            self.db, "greg@example.com", "greg",
            auth_tokens.hash_password("hunter2222"),
        )
        self.human = {
            "Authorization": "Bearer "
            + auth_tokens.create_access_token(
                auth_tokens.signing_secret(self.db), user["id"]
            )
        }
        self.root = {
            "Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "root-mgr")
        }
        self.impl = {
            "Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "root-impl")
        }
        self._original_runtime = server.runtime
        server.runtime = self.runtime

    def tearDown(self):
        server.runtime = self._original_runtime
        self.client.close()
        self.db.close()
        self.directory.cleanup()

    def test_human_appoints_root_child_assignment_report_and_cross_line_deny(self):
        appointed = self.client.post(
            "/api/conversations/root/lead",
            json={"attachment_id": "root-mgr"},
            headers=self.human,
        )
        self.assertEqual(appointed.status_code, 200)
        self.assertEqual(appointed.json()["attachment_id"], "root-mgr")

        child = self.client.post(
            "/api/conversations/root/children",
            json={"name": "Book"},
            headers=self.root,
        )
        self.assertEqual(child.status_code, 201)
        child_id = child.json()["conversation"]["id"]
        self.assertEqual(child.json()["conversation"]["parent_id"], "root")

        self.db.add_attachment(
            "child-mgr", child_id, "book-lead", "fake", ["fake"], "/tmp"
        )
        designated = self.client.post(
            f"/api/conversations/{child_id}/lead",
            json={"attachment_id": "child-mgr"},
            headers=self.root,
        )
        self.assertEqual(designated.status_code, 200)
        child_headers = {
            "Authorization": "Bearer "
            + auth_store.ensure_api_token(self.db, "child-mgr")
        }

        assigned = self.client.post(
            f"/api/conversations/{child_id}/messages",
            json={"body": "@book-lead prove the first spread"},
            headers=self.root,
        )
        self.assertEqual(assigned.status_code, 200)
        self.assertEqual(assigned.json()["sender"], "astra")
        self.assertIn("@book-lead", assigned.json()["body"])

        deposited = self.client.post(
            f"/api/conversations/{child_id}/reports",
            json={"body": "spread 1 is ready for review"},
            headers=child_headers,
        )
        self.assertEqual(deposited.status_code, 201)
        self.assertFalse(deposited.json()["notify"])
        self.assertEqual(deposited.json()["author_attachment_id"], "child-mgr")

        inbox = self.client.get(
            "/api/conversations/root/reports", headers=self.root
        )
        self.assertEqual(inbox.status_code, 200)
        self.assertEqual(len(inbox.json()), 1)
        report = inbox.json()[0]
        self.assertEqual(report["body"], "spread 1 is ready for review")
        self.assertEqual(report["child_conv_id"], child_id)
        acked = self.client.post(
            f"/api/conversations/root/reports/{report['id']}/ack",
            json={"revision": report["revision"]},
            headers=self.root,
        )
        self.assertEqual(acked.status_code, 200)
        self.assertIsNotNone(acked.json()["acknowledged_at"])

        refused = self.client.get(
            f"/api/conversations/{child_id}", headers=self.impl
        )
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(
            self.client.post(
                "/api/presets",
                json={"title": "x", "name": "tool", "adapter": "fake", "command": "fake"},
                headers=self.impl,
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post("/api/adapters/reload", headers=self.impl).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/api/attachments/root-mgr/compact", headers=self.impl
            ).status_code,
            403,
        )
