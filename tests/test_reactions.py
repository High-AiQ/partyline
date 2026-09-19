"""Message reaction persistence, authorization, events, and private delivery."""

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


class FakeSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


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

    def _live_process(self, name="sol"):
        attachment, _ = self._machine(name=name)
        recorder = Recorder(self.db.get_attachment(attachment["id"]))
        self.runtime.live[attachment["id"]] = recorder
        return attachment, recorder

    def _react(self, message, emoji="✅"):
        return self.client.post(
            f"/api/messages/{message['id']}/reactions", json={"emoji": emoji}
        )

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

    def _stored_lines(self):
        """Every stored row, including copies the human transcript now hides."""
        return [
            dict(row)
            for row in self.db._exec(
                "SELECT * FROM messages WHERE conv_id='line' ORDER BY id"
            ).fetchall()
        ]

    def _system_lines(self):
        """Every stored line, with whether it is addressed to one process."""
        return [
            (m["body"], m["sender_type"], m["audience_attachment_id"])
            for m in self._stored_lines()
        ]

    def test_person_reaction_wakes_the_process_with_an_addressed_private_copy(self):
        attachment, _ = self._machine()
        recorder = Recorder(self.db.get_attachment(attachment["id"]))
        self.runtime.live[attachment["id"]] = recorder
        message = self.db.add_message("line", "sol", "agent", "x" * 100)
        response = self.client.post(
            f"/api/messages/{message['id']}/reactions", json={"emoji": "✅"}
        )
        self.assertEqual(response.status_code, 200)
        # The target is woken at once — a reaction may be the whole answer.
        self.assertEqual(
            recorder.delivered[-1]["body"],
            "☺ greg reacted ✅ to your «" + "x" * 80 + "…»",
        )
        # The copy is stored addressed to that process alone: never a public
        # (unaddressed) system line in the room transcript.
        wake = self._stored_lines()[-1]
        self.assertEqual(wake["sender_type"], "system")
        self.assertEqual(wake["audience_attachment_id"], attachment["id"])
        for _body, sender_type, audience in self._system_lines():
            self.assertNotEqual((sender_type, audience), ("system", None))

    def test_human_transcript_excludes_the_reaction_notice(self):
        attachment, recorder = self._live_process()
        message = self.db.add_message("line", "sol", "agent", "found the answer")
        response = self._react(message)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(recorder.delivered), 1)  # the process got its copy
        page = self.client.get("/api/conversations/line/messages").json()
        self.assertEqual([m["body"] for m in page["messages"]], ["found the answer"])
        # The reaction itself is still on the message for humans.
        self.assertEqual(page["messages"][0]["reactions"][0]["emoji"], "✅")

    def test_human_transcript_page_after_excludes_the_reaction_notice(self):
        attachment, _ = self._live_process()
        message = self.db.add_message("line", "sol", "agent", "found the answer")
        self._react(message, "👀")
        page = self.client.get(
            f"/api/conversations/line/messages?after_id={message['id']}"
        ).json()
        self.assertEqual(page["messages"], [])

    def test_process_digest_includes_the_reaction_notice(self):
        attachment, _ = self._live_process()
        message = self.db.add_message("line", "sol", "agent", "found the answer")
        self._react(message)
        pending = self.db.messages_after("line", message["id"], "sol", attachment["id"])
        self.assertEqual(
            [m["body"] for m in pending],
            ["☺ greg reacted ✅ to your «found the answer»"],
        )
        other, _ = self._machine(name="kimi")
        self.assertEqual(
            self.db.messages_after("line", message["id"], "kimi", other["id"]), []
        )

    def test_browser_broadcast_excludes_the_reaction_notice(self):
        attachment, _ = self._live_process()
        message = self.db.add_message("line", "sol", "agent", "found the answer")
        socket = FakeSocket()
        self.runtime.sockets["line"] = {socket}
        self._react(message)
        kinds = [payload.get("type") for payload in socket.sent]
        self.assertNotIn("message", kinds)
        self.assertIn("reaction", kinds)

    def test_private_copies_that_are_not_reaction_notices_stay_human_visible(self):
        attachment, _ = self._machine()
        copy = self.db.add_message("line", "system", "system", "☏ sol went quiet")
        self.db._exec(
            "UPDATE messages SET audience_attachment_id=? WHERE id=?",
            (attachment["id"], copy["id"]),
        )
        page = self.client.get("/api/conversations/line/messages").json()
        self.assertIn("☏ sol went quiet", [m["body"] for m in page["messages"]])

    def test_a_reaction_to_a_stopped_process_wakes_and_posts_nothing(self):
        attachment, _ = self._machine()
        self.db.set_attachment_status(attachment["id"], "exited", attachment["runtime_owner"])
        message = self.db.add_message("line", "sol", "agent", "queued work")
        response = self.client.post(
            f"/api/messages/{message['id']}/reactions", json={"emoji": "👀"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [(body, sender) for body, sender, _ in self._system_lines()],
            [("queued work", "agent")],
        )

    def test_a_reaction_on_a_human_message_posts_and_wakes_nothing(self):
        attachment, _ = self._machine()
        recorder = Recorder(self.db.get_attachment(attachment["id"]))
        self.runtime.live[attachment["id"]] = recorder
        message = self.db.add_message("line", "greg", "human", "ship it")
        before = self._system_lines()
        response = self.client.post(
            f"/api/messages/{message['id']}/reactions", json={"emoji": "🎉"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._system_lines(), before)
        self.assertEqual(recorder.delivered, [])

    def test_an_agent_reaction_wakes_and_posts_nothing(self):
        attachment, token = self._machine(name="sol")
        _, other_token = self._machine(name="kimi")
        recorder = Recorder(self.db.get_attachment(attachment["id"]))
        self.runtime.live[attachment["id"]] = recorder
        message = self.db.add_message("line", "sol", "agent", "my work")
        before = self._system_lines()
        self.client.headers["Authorization"] = f"Bearer {other_token}"
        self.client.post(f"/api/messages/{message['id']}/reactions", json={"emoji": "✅"})
        self.assertEqual(self._system_lines(), before)
        self.assertEqual(recorder.delivered, [])
        self.client.headers["Authorization"] = f"Bearer {token}"

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

    def test_delete_removes_only_caller_and_validates_access(self):
        _, token = self._machine(name="sol")
        message = self.db.add_message("line", "greg", "human", "ship it")
        self.client.post(f"/api/messages/{message['id']}/reactions", json={"emoji": "🎉"})
        self.client.headers["Authorization"] = f"Bearer {token}"
        self.client.post(f"/api/messages/{message['id']}/reactions", json={"emoji": "🎉"})

        self.client.headers["Authorization"] = f"Bearer {self.tokens['greg']}"
        removed = self.client.delete(f"/api/messages/{message['id']}/reactions/🎉")
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(removed.json()["reactions"], [{
            "emoji": "🎉", "reactors": ["sol"], "mine": False,
        }])
        self.assertEqual(
            self.client.delete(f"/api/messages/{message['id']}/reactions/🔥").status_code,
            400,
        )

        _, other_token = self._machine("other", "worker")
        self.client.headers["Authorization"] = f"Bearer {other_token}"
        forbidden = self.client.delete(f"/api/messages/{message['id']}/reactions/🎉")
        self.assertEqual(forbidden.status_code, 403)
