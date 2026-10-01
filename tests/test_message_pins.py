"""Per-line message pin routes and their authority boundaries."""

from pathlib import Path
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.pin_routes import pin_router
from partyline.runtime import ChatRuntime


class MessagePinsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(Path(self.directory.name) / "partyline.db")
        self.db.create_conversation("line", "Line")
        self.db.create_conversation("other", "Other")
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(pin_router(self.runtime))
        self.client = TestClient(app)
        user = auth_store.create_user(
            self.db, "greg@example.com", "greg", auth_tokens.hash_password("hunter2222")
        )
        self.person = auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"]
        )
        self.client.headers["Authorization"] = f"Bearer {self.person}"
        self.message = self.db.add_message("line", "greg", "human", "a long source message")

    def tearDown(self):
        self.client.close()
        self.db.close()
        self.directory.cleanup()

    def _machine_token(self):
        attachment = self.db.add_attachment(
            "machine", "line", "worker", "fake", ["fake"], self.directory.name, "owner"
        )
        return auth_store.ensure_api_token(self.db, attachment["id"])

    def test_people_create_list_alias_clear_and_remove(self):
        created = self.client.post(
            "/api/conversations/line/pins", json={"message_id": self.message["id"]}
        )
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["message_text"], "a long source message")
        edited = self.client.put(
            f"/api/conversations/line/pins/{self.message['id']}",
            json={"alias": "Decision log"},
        )
        self.assertEqual(edited.json()["alias"], "Decision log")
        self.assertEqual(
            self.client.get("/api/conversations/line/pins").json()[0]["alias"],
            "Decision log",
        )
        cleared = self.client.put(
            f"/api/conversations/line/pins/{self.message['id']}", json={"alias": "  "}
        )
        self.assertIsNone(cleared.json()["alias"])
        removed = self.client.delete(f"/api/conversations/line/pins/{self.message['id']}")
        self.assertEqual(removed.json(), [])

    def test_alias_is_capped_and_message_must_belong_to_line(self):
        oversized = self.client.put(
            f"/api/conversations/line/pins/{self.message['id']}",
            json={"alias": "x" * 121},
        )
        self.assertEqual(oversized.status_code, 422)
        foreign = self.db.add_message("other", "greg", "human", "other line")
        response = self.client.post(
            "/api/conversations/line/pins", json={"message_id": foreign["id"]}
        )
        self.assertEqual(response.status_code, 404)

    def test_machines_can_read_pins_but_cannot_write(self):
        self.client.post(
            "/api/conversations/line/pins", json={"message_id": self.message["id"]}
        )
        self.client.headers["Authorization"] = f"Bearer {self._machine_token()}"
        self.assertEqual(self.client.get("/api/conversations/line/pins").status_code, 200)
        self.assertEqual(
            self.client.post(
                "/api/conversations/line/pins", json={"message_id": self.message["id"]}
            ).status_code,
            403,
        )

    def test_missing_source_is_returned_as_unavailable_and_line_purge_removes_pins(self):
        self.client.post(
            "/api/conversations/line/pins", json={"message_id": self.message["id"]}
        )
        self.db._exec("DELETE FROM messages WHERE id=?", (self.message["id"],))
        self.db._exec(
            "INSERT INTO message_pins(conv_id,message_id,alias,created_at) VALUES(?,?,?,?)",
            ("line", 999, None, 1),
        )
        stale = self.client.get("/api/conversations/line/pins").json()[0]
        self.assertFalse(stale["message_available"])
        self.db.delete_conversation("line")
        self.assertEqual(
            self.db._exec("SELECT * FROM message_pins WHERE conv_id='line'").fetchall(), []
        )
