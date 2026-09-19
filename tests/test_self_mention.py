"""Item 9: a machine message that would wake only its own credential is refused."""

import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens, server
from partyline.auth_guard import install_auth_guard
from partyline.conversation_routes import register_conversation_routes
from partyline.db import Db
from partyline.hierarchy_routes import hierarchy_router
from partyline.media import MediaStore
from partyline.message_routing import self_mention_reason
from partyline.runtime import ChatRuntime


class SelfMentionTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(hierarchy_router(self.runtime))

        async def fake_start(att, **kwargs):
            return att

        register_conversation_routes(
            app, self.runtime, MediaStore(self.db, self.directory.name + "/media"),
            None, {}, {}, fake_start,
        )
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.addCleanup(setattr, server, "runtime", server.runtime)
        self.addCleanup(setattr, server, "_start_attachment", server._start_attachment)
        server.runtime = self.runtime
        server._start_attachment = fake_start
        self.db.create_conversation("root", "Root")
        self.db.add_attachment("root-lead", "root", "terra", "fake", ["fake"], "/tmp")
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id='root-lead'")
        self.db.add_attachment("root-worker", "root", "dig", "fake", ["fake"], "/tmp")
        self.db._exec("UPDATE attachments SET status='running' WHERE id='root-worker'")
        user = auth_store.create_user(
            self.db, "person@example.com", "person", auth_tokens.hash_password("hunter2222"))
        self.human = {"Authorization": "Bearer " + auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])}
        self.captain = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "root-lead")}

    def post(self, body, headers=None):
        return self.client.post(
            "/api/conversations/root/messages", json={"body": body},
            headers=headers or self.captain)

    def stored(self):
        rows = self.db._exec(
            "SELECT id FROM messages WHERE sender_type='agent' AND sender='terra'"
        ).fetchall()
        return len(rows)

    def test_a_message_whose_only_live_mention_is_the_sender_is_refused(self):
        made = self.post("@terra hello, anyone there?")
        self.assertEqual(made.status_code, 422, made.text)
        self.assertIn("self-mention wakes nobody", made.json()["detail"])
        self.assertEqual(self.stored(), 0)  # refused before anything is stored

    def test_the_colon_form_of_the_sender_is_refused_too(self):
        made = self.post("terra: do the thing")
        self.assertEqual(made.status_code, 422, made.text)
        self.assertIn("self-mention wakes nobody", made.json()["detail"])

    def test_an_opening_assignment_to_the_own_credential_is_refused(self):
        made = self.post("@terra please have @dig build the thing")
        self.assertEqual(made.status_code, 422, made.text)
        self.assertIn("self-mention wakes nobody", made.json()["detail"])

    def test_a_genuinely_addressed_message_is_still_allowed(self):
        made = self.post("@terra and @dig: sync up on the plan")
        self.assertEqual(made.status_code, 200, made.text)
        made = self.post("@dig please build the thing")
        self.assertEqual(made.status_code, 200, made.text)
        made = self.post("no mentions at all, just a status note")
        self.assertEqual(made.status_code, 200, made.text)

    def test_a_dead_handle_alongside_the_self_mention_still_wakes_nobody(self):
        made = self.post("@terra and @ghost-handle: sync up")
        self.assertEqual(made.status_code, 422, made.text)

    def test_a_person_may_say_whatever_they_like(self):
        made = self.post("@terra hello", headers=self.human)
        self.assertEqual(made.status_code, 200, made.text)

    def test_all_rings_the_room_so_it_is_never_a_silent_self_wake(self):
        made = self.post("@all hands — @terra noting the deploy")
        self.assertEqual(made.status_code, 200, made.text)

    def test_a_human_handle_counts_as_someone_waking(self):
        auth_store.create_user(
            self.db, "greg@example.com", "greg", auth_tokens.hash_password("hunter2222"))
        made = self.post("@greg fyi, @terra will pause the line")
        self.assertEqual(made.status_code, 200, made.text)

    def test_the_reason_is_mechanical_not_prose_matching(self):
        from types import SimpleNamespace

        principal = SimpleNamespace(
            kind="machine", attachment_id="root-lead", name="terra", conv_id="root")
        reason = self_mention_reason(self.db, principal, "root", "@terra ping")
        self.assertIsNotNone(reason)
        plain = SimpleNamespace(
            kind="machine", attachment_id="root-worker", name="dig", conv_id="root")
        self.assertIsNotNone(self_mention_reason(self.db, plain, "root", "@dig ping"))
        self.assertIsNone(self_mention_reason(self.db, plain, "root", "@terra ping"))


if __name__ == "__main__":
    unittest.main()
