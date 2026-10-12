"""Cross-line speech: a sibling captain's post, and a forwarded quote (5.11)."""

import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.message_routes import message_router
from partyline.message_forward import forward_router, quote_forward
from partyline.media import MediaStore
from partyline.runtime import ChatRuntime


class CrossLineMessagingTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(message_router(self.runtime, MediaStore(
            self.db, f"{self.directory.name}/media")))
        app.include_router(forward_router(self.runtime))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        # root → {alpha, beta}; alpha → grandchild. Cousins never qualify.
        self.db.create_conversation("root", "Root")
        for conv, name, parent in (("alpha", "Alpha", "root"), ("beta", "Beta", "root"),
                                   ("grand", "Grand", "alpha")):
            self.db.create_conversation(conv, name)
            self.db._exec("UPDATE conversations SET parent_id=? WHERE id=?", (parent, conv))
        for att_id, name, conv in (("alpha-cap", "sol", "alpha"),
                                   ("alpha-worker", "gem", "alpha"),
                                   ("beta-cap", "luna", "beta"),
                                   ("grand-cap", "dig", "grand")):
            self.db.add_attachment(att_id, conv, name, "raw", ["raw"], "/tmp", att_id)
            self.db._exec("UPDATE attachments SET status='running' WHERE id=?", (att_id,))
        self.db._exec("UPDATE attachments SET is_lead=1 WHERE id IN "
                      "('alpha-cap', 'beta-cap', 'grand-cap')")

    def token(self, att_id):
        return {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, att_id)}

    def post(self, conv, body, att_id):
        return self.client.post(f"/api/conversations/{conv}/messages",
                                json={"body": body}, headers=self.token(att_id))

    def test_a_sibling_captain_posts_and_the_line_is_attributed(self):
        made = self.post("beta", "@luna heads up: the terrain slice lands today", "alpha-cap")
        self.assertEqual(made.status_code, 200, made.text)

        stored = [m for m in self.db.list_messages("beta") if m["sender"] == "sol"][-1]
        self.assertEqual(stored["source_conv_id"], "alpha")  # "via «Alpha»"
        self.assertIn("terrain slice", stored["body"])

    def test_a_sibling_worker_and_a_cousin_are_refused(self):
        worker = self.post("beta", "@luna hello", "alpha-worker")
        self.assertEqual(worker.status_code, 403)
        cousin = self.post("beta", "@luna hello", "grand-cap")
        self.assertEqual(cousin.status_code, 403)
        self.assertEqual(self.db.list_messages("beta"), [])

    def test_a_root_line_is_never_a_sibling(self):
        # The root has no parent, so nothing shares its (non-existent) one.
        made = self.post("root", "@anyone", "alpha-cap")
        self.assertEqual(made.status_code, 403)


class ForwardTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(message_router(self.runtime, MediaStore(
            self.db, f"{self.directory.name}/media")))
        app.include_router(forward_router(self.runtime))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.db.create_conversation("root", "Root")
        self.db.create_conversation("kid", "Kid")
        self.db._exec("UPDATE conversations SET parent_id='root' WHERE id='kid'")
        self.db.add_message("kid", "gem", "agent", "@lead the suite is green, 61 of 61")
        self.db.add_attachment("root-cap", "root", "sol", "raw", ["raw"], "/tmp", "rc")
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id='root-cap'")

    def token(self, att_id):
        return {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, att_id)}

    def forward(self, message_id, payload, att_id="root-cap", src="kid"):
        return self.client.post(
            f"/api/conversations/{src}/messages/{message_id}/forward",
            json=payload, headers=self.token(att_id))

    def test_the_quote_carries_the_author_and_the_line(self):
        made = self.forward(1, {"to": "root", "note": "for the record"})
        self.assertEqual(made.status_code, 200, made.text)

        stored = self.db.list_messages("root")[-1]
        self.assertIn("for the record", stored["body"])
        self.assertIn("↪ forwarded from «Kid» — gem said:", stored["body"])
        self.assertIn("@lead the suite is green, 61 of 61", stored["body"])

    def test_without_a_note_the_quote_stands_alone(self):
        made = self.forward(1, {"to": "root"})
        self.assertEqual(made.status_code, 200, made.text)
        stored = self.db.list_messages("root")[-1]
        self.assertTrue(stored["body"].startswith("↪ forwarded from «Kid»"))

    def test_read_without_write_and_unknown_messages_are_refused(self):
        # The forwarder has write on root and read on kid; a worker on kid
        # has read on kid but no write anywhere above.
        self.db.add_attachment("kid-worker", "kid", "gem2", "raw", ["raw"], "/tmp", "w")
        self.db._exec("UPDATE attachments SET status='running' WHERE id='kid-worker'")
        refused = self.forward(1, {"to": "root"}, att_id="kid-worker")
        self.assertEqual(refused.status_code, 403)
        missing = self.forward(99, {"to": "root"})
        self.assertEqual(missing.status_code, 404)
        nowhere = self.forward(1, {"to": "elsewhere"})
        self.assertEqual(nowhere.status_code, 404)  # unknown target line

    def test_the_quote_helper_is_pure_text(self):
        self.assertEqual(
            quote_forward("note", "Kid", "gem", "body"),
            "note\n\n↪ forwarded from «Kid» — gem said:\nbody")
        self.assertEqual(
            quote_forward("", "Kid", "gem", "body"),
            "↪ forwarded from «Kid» — gem said:\nbody")


if __name__ == "__main__":
    unittest.main()
