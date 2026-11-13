"""Person-owned line stars persist and update through the normal conversation wire."""

import tempfile
import unittest
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens
from partyline.auth_guard import install_auth_guard
from partyline.conversation_routes import register_conversation_routes
from partyline.conversation_stars import starred_ids
from partyline.db import Db
from partyline.hierarchy import create_child_conversation
from partyline.media import MediaStore
from partyline.runtime import ChatRuntime


class ConversationStarsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        self.runtime.broadcast_all = AsyncMock()
        self.db.create_conversation("parent", "Parent")
        create_child_conversation(self.db, "parent", "child", "Child")
        app = FastAPI()
        install_auth_guard(app, self.db)
        register_conversation_routes(
            app, self.runtime, MediaStore(self.db, f"{self.directory.name}/media"),
            None, {}, {}, AsyncMock(),
        )
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.people = []
        self.user_ids = []
        for number in (1, 2):
            user = auth_store.create_user(
                self.db, f"person{number}@example.com", f"person{number}",
                auth_tokens.hash_password("hunter2222"),
            )
            token = auth_tokens.create_access_token(auth_tokens.signing_secret(self.db), user["id"])
            self.people.append({"Authorization": f"Bearer {token}"})
            self.user_ids.append(user["id"])
        self.db.add_attachment("worker", "parent", "worker", "fake", ["fake"], "/tmp")
        self.process = {"Authorization": f"Bearer {auth_store.ensure_api_token(self.db, 'worker')}"}

    def test_stars_are_private_idempotent_and_included_in_the_list(self):
        path = "/api/conversations/child/star"
        self.assertEqual(self.client.put(path, headers=self.people[0]).json(), {"ok": True, "starred": True})
        self.assertEqual(self.client.put(path, headers=self.people[0]).status_code, 200)
        own = {
            line["id"]: line
            for line in self.client.get("/api/conversations", headers=self.people[0]).json()
        }
        other = {
            line["id"]: line
            for line in self.client.get("/api/conversations", headers=self.people[1]).json()
        }
        self.assertTrue(own["child"]["starred"])
        self.assertFalse(other["child"]["starred"])
        self.assertEqual(self.client.delete(path, headers=self.people[0]).status_code, 200)
        self.assertEqual(
            self.client.delete(path, headers=self.people[0]).json(),
            {"ok": True, "starred": False},
        )
        own = {
            line["id"]: line
            for line in self.client.get("/api/conversations", headers=self.people[0]).json()
        }
        self.assertFalse(own["child"]["starred"])
        self.assertEqual(self.runtime.broadcast_all.await_count, 2)

    def test_process_cannot_star_and_archived_stars_are_hidden_but_kept(self):
        path = "/api/conversations/child/star"
        self.assertEqual(self.client.put(path, headers=self.process).status_code, 403)
        machine_lines = self.client.get("/api/conversations", headers=self.process).json()
        self.assertTrue(all(not line["starred"] for line in machine_lines))
        self.assertEqual(
            self.client.put("/api/conversations/missing/star", headers=self.people[0]).status_code,
            404,
        )
        self.client.put(path, headers=self.people[0])
        self.db.archive_conversation("child")
        lines = self.client.get("/api/conversations", headers=self.people[0]).json()
        self.assertNotIn("child", [line["id"] for line in lines])
        self.assertIn("child", starred_ids(self.db, self.user_ids[0]))
