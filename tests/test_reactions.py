"""Message reaction persistence, authorization, events, and process wakes."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.media import MediaStore
from partyline.message_routes import message_router
from partyline.reaction_routes import reaction_router
from partyline.runtime import ChatRuntime


class Recorder:
    def __init__(self, attachment):
        self.att = attachment
        self.delivered = []

    async def deliver(self, messages):
        self.delivered.extend(messages)


class ReactionRoutesTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(Path(self.directory.name) / "partyline.db")
        self.db.create_conversation("line", "Line")
        self.db.create_conversation("other", "Other")
        self.runtime = ChatRuntime(self.db)
        self.media = MediaStore(self.db, Path(self.directory.name) / "media")
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(message_router(self.runtime, self.media))
        app.include_router(reaction_router(self.runtime))
        self.client = TestClient(app)
        self.tokens = {}
        self.tokens["greg"] = self._user_token("greg")
        self.client.headers["Authorization"] = f"Bearer {self.tokens['greg']}"

    def tearDown(self):
        self.client.close()
        self.db.close()
        self.directory.cleanup()

    def _user_token(self, handle):
        user = auth_store.create_user(
            self.db,
            f"{handle}@example.com",
            handle,
            auth_tokens.hash_password("hunter2222"),
        )
        return auth_tokens.create_access_token(auth_tokens.signing_secret(self.db), user["id"])

    def _machine(self, conv_id="line", name="sol"):
        att = self.db.add_attachment(
            f"{name}-att", conv_id, name, "fake", ["fake"], self.directory.name, f"{name}-owner"
        )
        self.db.set_attachment_status(att["id"], "running", att["runtime_owner"])
        token = auth_store.ensure_api_token(self.db, att["id"])
        return att, token

    def test_toggle_response_history_and_uniqueness(self):
        message = self.db.add_message("line", "sol", "agent", "found the answer")
        added = self.client.post(
            f"/api/messages/{message['id']}/reactions", json={"emoji": "✅"}
        )
        self.assertEqual(added.status_code, 200)
        self.assertEqual(added.json()["reactions"], [{
            "emoji": "✅", "reactors": ["greg"], "mine": True,
        }])
        repeated = self.client.post(
            f"/api/messages/{message['id']}/reactions", json={"emoji": "✅"}
        )
        self.assertEqual(repeated.json()["reactions"], [])
        rows = self.db._exec("SELECT * FROM reactions WHERE message_id=?", (message["id"],)).fetchall()
        self.assertEqual(rows, [])

    def test_unknown_emoji_is_bad_request(self):
        message = self.db.add_message("line", "sol", "agent", "found the answer")
        response = self.client.post(
            f"/api/messages/{message['id']}/reactions", json={"emoji": "🔥"}
        )
        self.assertEqual(response.status_code, 400)

    def test_machine_from_another_line_is_forbidden(self):
        _, token = self._machine("other", "worker")
        message = self.db.add_message("line", "sol", "agent", "found the answer")
        self.client.headers["Authorization"] = f"Bearer {token}"
        response = self.client.post(
            f"/api/messages/{message['id']}/reactions", json={"emoji": "👀"}
        )
        self.assertEqual(response.status_code, 403)

    def test_person_reaction_wakes_process_with_private_one_line_message(self):
        attachment, _ = self._machine()
        recorder = Recorder(self.db.get_attachment(attachment["id"]))
        self.runtime.live[attachment["id"]] = recorder
        message = self.db.add_message("line", "sol", "agent", "x" * 100)
        response = self.client.post(
            f"/api/messages/{message['id']}/reactions", json={"emoji": "✅"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            recorder.delivered[-1]["body"],
            "☺ greg reacted ✅ to your «" + "x" * 80 + "…»",
        )
        self.assertEqual(self.db.list_messages("line")[-1]["body"], recorder.delivered[-1]["body"])

    def test_process_reaction_broadcasts_without_posting_chat(self):
        attachment, token = self._machine()
        self.runtime.broadcast = AsyncMock()
        message = self.db.add_message("line", "greg", "human", "ship it")
        before = len(self.db.list_messages("line"))
        self.client.headers["Authorization"] = f"Bearer {token}"
        response = self.client.post(
            f"/api/messages/{message['id']}/reactions", json={"emoji": "🎉"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.db.list_messages("line")), before)
        event = self.runtime.broadcast.await_args.args[1]
        self.assertEqual(event.type, "reaction")
        self.assertEqual(event.message_id, message["id"])

    def test_history_includes_reactions_for_the_caller(self):
        message = self.db.add_message("line", "sol", "agent", "found the answer")
        self.client.post(f"/api/messages/{message['id']}/reactions", json={"emoji": "👀"})
        page = self.client.get("/api/conversations/line/messages")
        self.assertEqual(page.json()["messages"][-1]["reactions"][0]["mine"], True)
