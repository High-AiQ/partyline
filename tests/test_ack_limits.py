"""Finding 2.4: the third bare exchange between two workers is not sent."""

import asyncio
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens
from partyline.ack_limits import pingpong_refusal
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.media import MediaStore
from partyline.message_routes import message_router
from partyline.runtime import ChatRuntime


class AckLimitsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.db.create_conversation("line", "Line")
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(message_router(self.runtime, MediaStore(
            self.db, f"{self.directory.name}/media")))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        for att_id, name in (("sol", "sol"), ("haiku", "haiku")):
            self.db.add_attachment(att_id, "line", name, "fake", ["fake"], "/tmp", att_id)
            self.db._exec("UPDATE attachments SET status='running' WHERE id=?", (att_id,))
        user = auth_store.create_user(
            self.db, "greg@example.com", "greg", auth_tokens.hash_password("hunter2222"))
        self.human = {"Authorization": "Bearer " + auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])}
        self.sol = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "sol")}
        self.haiku = {"Authorization": "Bearer " + auth_store.ensure_api_token(
            self.db, "haiku")}

    def post(self, body, headers):
        return self.client.post("/api/conversations/line/messages",
                                json={"body": body}, headers=headers)

    def bare_exchange(self):
        """Two real messages, each echoing the other back."""
        self.post("@haiku suite at 13 of 61", self.sol)
        self.post("@sol standing by", self.haiku)

    def test_the_third_bare_exchange_is_refused_with_429(self):
        self.bare_exchange()

        third = self.post("@haiku suite at 21 of 61", self.sol)

        self.assertEqual(third.status_code, 429, third.text)
        self.assertIn("ack ping-pong", third.json()["detail"])
        self.assertIn("@haiku's last message", third.json()["detail"])
        self.assertIn("react", third.json()["detail"])
        bodies = [m["body"] for m in self.db.list_messages("line")]
        self.assertNotIn("@haiku suite at 21 of 61", bodies)

    def test_a_file_or_reaction_in_between_resets_the_count(self):
        self.bare_exchange()
        echo = [m for m in self.db.list_messages("line") if m["sender"] == "haiku"][-1]

        self.db._exec(
            "INSERT INTO images(id, conv_id, message_id, mime, width, height,"
            " bytes, path, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            ("img1", "line", echo["id"], "image/png", 1, 1, 1, "x.png", echo["created_at"] + 1))

        after_file = self.post("@haiku suite at 21 of 61", self.sol)
        self.assertEqual(after_file.status_code, 200, after_file.text)

    def test_a_reaction_in_between_resets_the_count(self):
        self.bare_exchange()
        echo = [m for m in self.db.list_messages("line") if m["sender"] == "haiku"][-1]
        self.db._exec(
            "INSERT INTO reactions(message_id, reactor, reactor_type, emoji, created_at)"
            " VALUES (?,?,?,?,?)",
            (echo["id"], "greg", "human", "\U0001f440", echo["created_at"] + 1))

        after = self.post("@haiku suite at 21 of 61", self.sol)

        self.assertEqual(after.status_code, 200, after.text)

    def test_a_captains_mention_is_never_refused(self):
        self.db.add_attachment("cap", "line", "astra", "fake", ["fake"], "/tmp", "cap")
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id='cap'")
        captain = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "cap")}
        for _ in range(4):  # a worker-captain ping-pong that must always ring
            self.assertEqual(self.post("@astra review this", self.haiku).status_code, 200)
            self.assertEqual(self.post("@haiku review this", captain).status_code, 200)

    def test_a_person_is_never_refused(self):
        self.bare_exchange()
        for _ in range(3):
            made = self.post("@haiku keep going", self.human)
            self.assertEqual(made.status_code, 200, made.text)

    def test_differing_texts_still_count_until_something_real_happens(self):
        # The observed failure was two *different* texts alternating ("standing
        # by" / "suite at 13 of 61"); the detector is content-blind by design —
        # only real events (file, reaction, person, third process, accept)
        # break the streak.
        self.bare_exchange()

        after = self.post("@haiku the build is red", self.sol)

        self.assertEqual(after.status_code, 429, after.text)

    def test_a_third_process_in_between_breaks_the_streak(self):
        self.bare_exchange()
        self.db.add_attachment("glm", "line", "glm", "fake", ["fake"], "/tmp", "glm")
        third = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "glm")}
        self.post("@sol handoff notes", third)

        after = self.post("@haiku suite at 21 of 61", self.sol)

        self.assertEqual(after.status_code, 200, after.text)

    def test_the_capture_path_stores_but_does_not_deliver(self):
        deliveries = []

        class Adapter:
            def __init__(self, att):
                self.att = att

            async def deliver(self, messages):
                deliveries.append(messages)
                return True

        self.runtime.live["haiku"] = Adapter(self.db.get_attachment("haiku"))
        self.runtime.live["sol"] = Adapter(self.db.get_attachment("sol"))
        for body, sender in (("@haiku suite at 13 of 61", "sol"),
                             ("@sol standing by", "haiku")):
            stored = self.db.add_message("line", sender, "agent", body)
            asyncio.run(self.runtime.route_mentions("line", stored))
        self.assertEqual(len(deliveries), 2)  # the first two land

        third = self.db.add_message("line", "sol", "agent", "@haiku suite at 21 of 61")
        asyncio.run(self.runtime.route_mentions("line", third))

        self.assertEqual(len(deliveries), 2)  # the third is not delivered
        bodies = [m["body"] for m in self.db.list_messages("line")]
        self.assertIn("@haiku suite at 21 of 61", bodies)  # the transcript keeps it
        notices = [b for b in bodies if "ack ping-pong" in b and b.startswith("⚠")]
        self.assertEqual(len(notices), 1)
        self.assertIn("@sol", notices[0])
        self.assertIn("@haiku", notices[0])

    def test_the_detector_is_pure_and_stateless(self):
        self.bare_exchange()
        self.assertEqual(pingpong_refusal(self.db, "line", "sol", "@haiku ok"), "haiku")
        # nothing was stored by the query: running it again gives the same answer
        self.assertEqual(pingpong_refusal(self.db, "line", "sol", "@haiku ok"), "haiku")
        # @all and two live addressees are conversation, not a bare ack
        self.db.add_attachment("glm", "line", "glm", "fake", ["fake"], "/tmp", "glm")
        self.db._exec("UPDATE attachments SET status='running' WHERE id='glm'")
        self.assertIsNone(pingpong_refusal(self.db, "line", "sol", "@haiku @glm ok"))
        self.assertIsNone(pingpong_refusal(self.db, "line", "sol", "@all ok"))


if __name__ == "__main__":
    unittest.main()
